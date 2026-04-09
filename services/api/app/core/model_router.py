from __future__ import annotations

import json
import os
import re
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
                "timeout_sec": _pick_int(primary_cfg.get("timeout_sec"), "QWEN_TIMEOUT_SEC", 180),
            },
            "secondary": {
                "slot": "secondary",
                "name": secondary_name,
                "base": _pick(secondary_cfg.get("base_url"), "MINIMAX_API_BASE", "").rstrip("/"),
                "key": _pick(secondary_cfg.get("api_key"), "MINIMAX_API_KEY", ""),
                "model": _pick(secondary_cfg.get("model"), "MINIMAX_MODEL", "MiniMax-M1"),
                "timeout_sec": _pick_int(secondary_cfg.get("timeout_sec"), "MINIMAX_TIMEOUT_SEC", 180),
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
        payload_base = {
            "model": model,
            "temperature": temperature,
            "max_tokens": 4096,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        payloads = [
            {**payload_base, "response_format": {"type": "json_object"}},
            payload_base,
        ]
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        errors: list[str] = []

        for idx, payload in enumerate(payloads, start=1):
            try:
                res = requests.post(url, json=payload, headers=headers, timeout=(8, timeout_sec))
            except Exception as e:
                errors.append(f"attempt{idx}: network_error={e}")
                break

            if not res.ok:
                body = (res.text or "")[:300]
                errors.append(f"attempt{idx}: status={res.status_code}, body={body}")
                if idx == 1 and res.status_code in {400, 404, 415, 422}:
                    continue
                break

            try:
                data = res.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                body = (res.text or "")[:300]
                errors.append(f"attempt{idx}: invalid_response={e}, body={body}")
                if idx == 1:
                    continue
                break

        raise RuntimeError("Model API call failed: " + " | ".join(errors))

    @staticmethod
    def safe_json(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            # Handle fenced outputs like ```json ... ```
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()

        # Fast path: content is already a clean JSON object.
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
            raise ValueError("Model response is valid JSON but not a JSON object")
        except Exception:
            pass

        # Fallback: extract the first decodable JSON object and ignore trailing junk.
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            start = match.start()
            try:
                obj, _end = decoder.raw_decode(text[start:])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue

        raise ValueError("Unable to parse JSON object from model response")

    def _call_slot(self, slot: str, system: str, user: str) -> dict[str, Any]:
        p = self.providers.get(slot)
        if not p:
            raise RuntimeError(f"Unknown provider slot: {slot}")

        try:
            content = self._chat(
                base=p["base"],
                key=p["key"],
                model=p["model"],
                system=system,
                user=user,
                timeout_sec=p["timeout_sec"],
            )
            self._emit_trace(
                slot=slot,
                provider_name=p.get("name") or slot,
                model=p.get("model") or "",
                system=system,
                user=user,
                response_text=content,
            )
            return self.safe_json(content)
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
            content = self._chat(
                base=p["base"],
                key=p["key"],
                model=p["model"],
                system=system,
                user=user,
                timeout_sec=p["timeout_sec"],
                temperature=0,
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
