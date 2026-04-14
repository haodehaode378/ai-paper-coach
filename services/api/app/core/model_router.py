from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests


class ModelRouter:
    def __init__(
        self,
        model_config: dict[str, Any] | None = None,
        trace_hook: Any | None = None,
        trace_phase: str = "",
    ) -> None:
        cfg = model_config or {}
        self.trace_hook = trace_hook
        self.trace_phase = trace_phase
        use_env = not bool(cfg)

        def _first_provider_cfg(*keys: str) -> dict[str, Any]:
            for key in keys:
                value = cfg.get(key)
                if isinstance(value, dict) and value:
                    return value
            return {}

        def _pick(cfg_value: Any, env_name: str, default: str = "") -> str:
            if isinstance(cfg_value, str) and cfg_value.strip():
                return cfg_value.strip()
            if use_env:
                env_val = (os.getenv(env_name, "") or "").strip()
                if env_val:
                    return env_val
            return default

        def _pick_int(cfg_value: Any, env_name: str, default: int) -> int:
            raw = None
            if cfg_value is not None:
                raw = str(cfg_value).strip()
            elif use_env:
                raw = (os.getenv(env_name, "") or "").strip() or None
            if not raw:
                return default
            try:
                v = int(raw)
                return v if v > 0 else default
            except Exception:
                return default

        primary_cfg = _first_provider_cfg("primary", "provider_a", "qwen")
        secondary_cfg = _first_provider_cfg("secondary", "provider_b", "minimax")

        primary_name = _pick(primary_cfg.get("name"), "PRIMARY_PROVIDER_NAME", "模型A")
        secondary_name = _pick(secondary_cfg.get("name"), "SECONDARY_PROVIDER_NAME", "模型B")

        self.providers: dict[str, dict[str, Any]] = {
            "primary": {
                "slot": "primary",
                "name": primary_name,
                "base": _pick(primary_cfg.get("base_url"), "QWEN_API_BASE", "").rstrip("/"),
                "key": _pick(primary_cfg.get("api_key"), "QWEN_API_KEY", ""),
                "model": _pick(primary_cfg.get("model"), "QWEN_MODEL", "qwen-plus"),
                "timeout_sec": _pick_int(primary_cfg.get("timeout_sec"), "QWEN_TIMEOUT_SEC", 90),
            },
            "secondary": {
                "slot": "secondary",
                "name": secondary_name,
                "base": _pick(secondary_cfg.get("base_url"), "MINIMAX_API_BASE", "").rstrip("/"),
                "key": _pick(secondary_cfg.get("api_key"), "MINIMAX_API_KEY", ""),
                "model": _pick(secondary_cfg.get("model"), "MINIMAX_MODEL", "MiniMax-M1"),
                "timeout_sec": _pick_int(secondary_cfg.get("timeout_sec"), "MINIMAX_TIMEOUT_SEC", 300),
            },
        }

        # Backward-compatible fields used by existing code paths.
        self.qwen_base = self.providers["primary"]["base"]
        self.qwen_key = self.providers["primary"]["key"]
        self.qwen_model = self.providers["primary"]["model"]
        self.qwen_timeout_sec = self.providers["primary"]["timeout_sec"]

        self.minimax_base = self.providers["secondary"]["base"]
        self.minimax_key = self.providers["secondary"]["key"]
        self.minimax_model = self.providers["secondary"]["model"]
        self.minimax_timeout_sec = self.providers["secondary"]["timeout_sec"]

    @staticmethod
    def _build_chat_url(base: str) -> str:
        if not base:
            return ""
        normalized = base.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        return f"{normalized}/chat/completions"

    @staticmethod
    def _is_kimi_model(base: str, model: str) -> bool:
        base_l = (base or "").lower()
        model_l = (model or "").lower()
        return ("moonshot.cn" in base_l) or ("kimi" in model_l)

    def _resolve_temperature(self, base: str, model: str, *, for_ping: bool = False) -> float:
        # Kimi models currently require temperature=1.
        if self._is_kimi_model(base, model):
            return 1.0
        return 0.0 if for_ping else 0.2

    def _resolve_timeout(self, base: str, model: str, configured_timeout: int, *, for_ping: bool = False) -> int:
        if self._is_kimi_model(base, model):
            # Analyze/Review/Finalize can be long on Kimi; keep ping short but runtime longer.
            return max(configured_timeout, 180) if not for_ping else max(min(configured_timeout, 90), 30)
        return configured_timeout

    def _resolve_max_tokens(self) -> int:
        phase = (self.trace_phase or "").lower()
        if phase in {"review", "finalize", "repair"}:
            return 12000
        if phase == "analyze":
            return 6000
        return 2048

    @staticmethod
    def _looks_like_error_payload(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        keys = set(data.keys())
        if not keys:
            return True
        if keys.issubset({"error", "status", "message", "detail"}):
            return True
        return False

    def provider_info(self, slot: str) -> dict[str, Any]:
        p = self.providers.get(slot, {})
        return {
            "slot": slot,
            "name": p.get("name") or slot,
            "base_url": p.get("base") or "",
            "model": p.get("model") or "",
            "timeout_sec": p.get("timeout_sec") or 0,
        }

    def _chat(
        self,
        *,
        base: str,
        key: str,
        model: str,
        system: str,
        user: str,
        timeout_sec: int = 180,
        temperature: float = 0.2,
    ) -> str:
        if not base or not key:
            raise RuntimeError("Missing model API configuration")

        url = self._build_chat_url(base)
        messages = []
        if isinstance(system, str) and system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload_base = {
            "model": model,
            "temperature": temperature,
            "max_tokens": self._resolve_max_tokens(),
            "messages": messages,
        }

        # Kimi-k2.5 has strict limitations with JSON mode and temperature.
        # Skip JSON mode entirely for Kimi to avoid API errors.
        is_kimi_k25 = self._is_kimi_model(base, model)
        
        if is_kimi_k25:
            # For Kimi, use standard format only (no JSON mode)
            payloads = [payload_base]
        else:
            payloads = [
                {**payload_base, "response_format": {"type": "json_object"}},
                payload_base,
            ]
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        errors: list[str] = []

        for idx, payload in enumerate(payloads, start=1):
            # Retry logic for temporary errors (429, 503, 504)
            max_retries = 3
            base_delay = 2  # seconds
            
            for retry in range(max_retries):
                try:
                    res = requests.post(url, json=payload, headers=headers, timeout=(8, timeout_sec))
                except Exception as e:
                    errors.append(f"attempt{idx}: network_error={e}")
                    break

                # Some providers return incorrect charset headers (e.g. latin-1) even for UTF-8 JSON.
                # Force UTF-8 fallback for non-explicit/legacy encodings to avoid mojibake.
                enc = (res.encoding or "").lower().strip()
                if not enc or enc in {"iso-8859-1", "latin-1", "ascii"}:
                    res.encoding = "utf-8"

                if not res.ok:
                    body = (res.text or "")[:300]
                    status_code = res.status_code
                    
                    # Handle temporary service errors with exponential backoff
                    if status_code in {429, 503, 504} and retry < max_retries - 1:
                        # Extract Retry-After header if available
                        retry_after = res.headers.get("Retry-After")
                        if retry_after:
                            try:
                                wait_time = float(retry_after)
                            except ValueError:
                                wait_time = base_delay * (2 ** retry)
                        else:
                            wait_time = base_delay * (2 ** retry)
                        
                        errors.append(f"attempt{idx}-retry{retry+1}: status={status_code}, waiting {wait_time:.1f}s")
                        time.sleep(min(wait_time, 30))  # Cap wait time at 30 seconds
                        continue
                    
                    # For other 4xx errors on first payload, try next payload
                    errors.append(f"attempt{idx}: status={status_code}, body={body}")
                    if idx == 1 and status_code in {400, 404, 415, 422}:
                        break  # Exit retry loop, try next payload
                    break  # Exit retry loop

                try:
                    data = res.json()
                    return data["choices"][0]["message"]["content"]
                except Exception as e:
                    body = (res.text or "")[:300]
                    errors.append(f"attempt{idx}: invalid_response={e}, body={body}")
                    if idx == 1:
                        break  # Exit retry loop, try next payload
                    break  # Exit retry loop
            
            # If we exhausted retries on first payload with non-retryable error, try next
            if idx == 1 and any(f"attempt{idx}: status=" in e for e in errors):
                continue

        raise RuntimeError("Model API call failed: " + " | ".join(errors))

    @staticmethod
    def safe_json(text: str) -> dict[str, Any]:
        text = (text or "").strip()
        # Remove reasoning blocks like <think>...</think> when providers leak them.
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
        # Some providers may return an unclosed <think> block; trim it from head.
        text = re.sub(r"^\s*<think>[\s\S]*?(?:</think>|(?=\{)|$)", "", text, flags=re.IGNORECASE).strip()
        if text.startswith("```"):
            # Handle fenced outputs like ```json ... ```
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()

        def _loads_obj(raw: str) -> dict[str, Any] | None:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except Exception:
                return None
            return None

        def _obj_score(obj: dict[str, Any]) -> int:
            target_keys = {
                "paper_meta",
                "three_minute_summary",
                "teach_classmate",
                "reproduction_guide",
                "reading_qa",
                "evidence_refs",
                "change_log",
                "missing_points",
                "unclear_terms",
                "risky_claims",
                "patch_suggestions",
            }
            return sum(1 for k in obj.keys() if k in target_keys)

        hit = _loads_obj(text)
        if hit is not None:
            return hit

        candidate = text.strip()
        if candidate.startswith("{"):
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            open_cnt = candidate.count("{")
            close_cnt = candidate.count("}")
            if open_cnt > close_cnt:
                candidate = candidate + ("}" * (open_cnt - close_cnt))
            hit = _loads_obj(candidate)
            if hit is not None:
                return hit

        decoder = json.JSONDecoder()
        best_obj: dict[str, Any] | None = None
        best_score = -1
        best_size = -1
        for match in re.finditer(r"\{", text):
            start_idx = match.start()
            piece = text[start_idx:]
            piece = re.sub(r",\s*([}\]])", r"\1", piece)
            try:
                obj, _end = decoder.raw_decode(piece)
                if isinstance(obj, dict):
                    score = _obj_score(obj)
                    size = len(json.dumps(obj, ensure_ascii=False))
                    if score > best_score or (score == best_score and size > best_size):
                        best_obj = obj
                        best_score = score
                        best_size = size
            except Exception:
                continue

        if best_obj is not None:
            return best_obj

        raise ValueError("Unable to parse JSON object from model response")
    def _chat_stream(self, *, base: str, key: str, model: str, system: str, user: str, timeout_sec: int = 180, temperature: float = 0.2):
        if not base or not key:
            raise RuntimeError("Missing model API configuration")

        url = self._build_chat_url(base)
        messages = []
        if isinstance(system, str) and system.strip():
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": self._resolve_max_tokens(),
            "messages": messages,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

        with requests.post(url, json=payload, headers=headers, timeout=(8, timeout_sec), stream=True) as res:
            # Streaming endpoints may advertise wrong charset; keep text decode deterministic.
            enc = (res.encoding or "").lower().strip()
            if not enc or enc in {"iso-8859-1", "latin-1", "ascii"}:
                res.encoding = "utf-8"

            if not res.ok:
                body = (res.text or "")[:300]
                raise RuntimeError(f"status={res.status_code}, body={body}")

            for raw_line in res.iter_lines(decode_unicode=False):
                if not raw_line:
                    continue
                if isinstance(raw_line, bytes):
                    try:
                        line = raw_line.decode("utf-8")
                    except Exception:
                        line = raw_line.decode(res.encoding or "utf-8", errors="replace")
                else:
                    line = str(raw_line)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue

                choices = data.get("choices") or []
                if not choices:
                    continue
                choice = choices[0] or {}
                delta = choice.get("delta") or {}
                content = delta.get("content")

                if isinstance(content, list):
                    text = "".join(
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict)
                    )
                elif isinstance(content, str):
                    text = content
                else:
                    message = choice.get("message") or {}
                    text = message.get("content") if isinstance(message, dict) else ""

                if text:
                    yield text

    def chat_text(self, *, slot: str = "primary", system: str = "", user: str = "") -> str:
        p = self.providers.get(slot)
        if not p:
            raise RuntimeError(f"Unknown provider slot: {slot}")

        try:
            timeout_sec = self._resolve_timeout(p["base"], p["model"], p["timeout_sec"], for_ping=False)
            temperature = self._resolve_temperature(p["base"], p["model"], for_ping=False)
            content = self._chat(
                base=p["base"],
                key=p["key"],
                model=p["model"],
                system=system,
                user=user,
                timeout_sec=timeout_sec,
                temperature=temperature,
            )
            text = (content or "").strip()
            if not text:
                raise RuntimeError("empty_model_output")
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                response_text=text,
            )
            return text
        except Exception as e:
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                error_text=str(e),
            )
            raise RuntimeError(
                f"{e} | slot={slot} | provider={p.get('name') or slot} | base_url={p.get('base') or '<empty>'} | model={p.get('model') or '<empty>'}"
            ) from e

    def chat_text_stream(self, *, slot: str = "primary", system: str = "", user: str = ""):
        p = self.providers.get(slot)
        if not p:
            raise RuntimeError(f"Unknown provider slot: {slot}")

        collected = []
        try:
            timeout_sec = self._resolve_timeout(p["base"], p["model"], p["timeout_sec"], for_ping=False)
            temperature = self._resolve_temperature(p["base"], p["model"], for_ping=False)
            for chunk in self._chat_stream(
                base=p["base"],
                key=p["key"],
                model=p["model"],
                system=system,
                user=user,
                timeout_sec=timeout_sec,
                temperature=temperature,
            ):
                collected.append(chunk)
                yield chunk
            full_text = "".join(collected).strip()
            if not full_text:
                raise RuntimeError("empty_model_output")
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                response_text=full_text,
            )
        except Exception as e:
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                error_text=str(e),
            )
            raise RuntimeError(
                f"{e} | slot={slot} | provider={p.get('name') or slot} | base_url={p.get('base') or '<empty>'} | model={p.get('model') or '<empty>'}"
            ) from e
    def _call_slot(self, slot: str, system: str, user: str) -> dict[str, Any]:
        p = self.providers.get(slot)
        if not p:
            raise RuntimeError(f"Unknown provider slot: {slot}")

        try:
            timeout_sec = self._resolve_timeout(p["base"], p["model"], p["timeout_sec"], for_ping=False)
            temperature = self._resolve_temperature(p["base"], p["model"], for_ping=False)
            content = self._chat(
                base=p["base"],
                key=p["key"],
                model=p["model"],
                system=system,
                user=user,
                timeout_sec=timeout_sec,
                temperature=temperature,
            )
            if not (content or "").strip() or (content or "").strip() in {"-", "—"}:
                raise RuntimeError("empty_model_output")
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                response_text=content,
            )
            try:
                parsed = self.safe_json(content)
                if self._looks_like_error_payload(parsed):
                    raise RuntimeError("invalid_json_payload")
                return parsed
            except Exception:
                repair_system = "你上一次输出不是合法 JSON。现在只输出一个合法 JSON 对象，不要任何解释和代码块。"
                repair_source = (content or "").strip()[:12000]
                if not repair_source:
                    raise RuntimeError("empty_model_output_for_json_repair")
                repair_user = f"请把下面文本修复为合法 JSON 对象：\n\n{repair_source}"
                repaired = self._chat(
                    base=p["base"],
                    key=p["key"],
                    model=p["model"],
                    system=repair_system,
                    user=repair_user,
                    timeout_sec=min(timeout_sec, 120),
                    temperature=self._resolve_temperature(p["base"], p["model"], for_ping=False),
                )
                self._emit_trace(
                    slot=slot,
                    provider_name=p.get("name") or slot,
                    model=p.get("model") or "",
                    system=repair_system,
                    user=repair_user,
                    response_text=repaired,
                )
                parsed = self.safe_json(repaired)
                if self._looks_like_error_payload(parsed):
                    raise RuntimeError("invalid_json_payload_after_repair")
                return parsed
        except Exception as e:
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                error_text=str(e),
            )
            raise RuntimeError(
                f"{e} | slot={slot} | provider={p.get('name') or slot} | base_url={p.get('base') or '<empty>'} | model={p.get('model') or '<empty>'}"
            ) from e
    def ping_slot(self, slot: str, system: str = "", user: str = "ping") -> str:
        p = self.providers.get(slot)
        if not p:
            raise RuntimeError(f"Unknown provider slot: {slot}")

        try:
            ping_system = system if isinstance(system, str) and system.strip() else "You are a helpful assistant."
            content = self._chat(
                base=p["base"],
                key=p["key"],
                model=p["model"],
                system=ping_system,
                user=user,
                timeout_sec=self._resolve_timeout(p["base"], p["model"], p["timeout_sec"], for_ping=True),
                temperature=self._resolve_temperature(p["base"], p["model"], for_ping=True),
            )
            text = (content or "").strip()
            if not text:
                raise RuntimeError("Model returned empty content")
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                response_text=text,
            )
            return text
        except Exception as e:
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                error_text=str(e),
            )
            raise RuntimeError(
                f"{e} | slot={slot} | provider={p.get('name') or slot} | base_url={p.get('base') or '<empty>'} | model={p.get('model') or '<empty>'}"
            ) from e

    def _emit_trace(
        self,
        *,
        slot: str,
        provider_name: str,
        model: str,
        system: str,
        user: str,
        response_text: str | None = None,
        error_text: str | None = None,
    ) -> None:
        if not self.trace_hook:
            return
        self.trace_hook(
            {
                "phase": self.trace_phase,
                "provider_slot": slot,
                "provider_name": provider_name,
                "model": model,
                "request_system": system,
                "request_user": user,
                "response_text": response_text,
                "error_text": error_text,
            }
        )

    def primary(self, system: str, user: str) -> dict[str, Any]:
        return self._call_slot("primary", system, user)

    def secondary(self, system: str, user: str) -> dict[str, Any]:
        return self._call_slot("secondary", system, user)

    # Backward-compatible aliases.
    def qwen(self, system: str, user: str) -> dict[str, Any]:
        return self.primary(system, user)

    def minimax(self, system: str, user: str) -> dict[str, Any]:
        return self.secondary(system, user)


