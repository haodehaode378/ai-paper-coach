from __future__ import annotations

import json
import os
import re
from typing import Any

import requests


class ModelRouter:
    def __init__(self, model_config: dict[str, Any] | None = None) -> None:
        cfg = model_config or {}
        qwen_cfg = cfg.get("qwen", {}) or {}
        minimax_cfg = cfg.get("minimax", {}) or {}

        self.qwen_base = (qwen_cfg.get("base_url") or os.getenv("QWEN_API_BASE", "")).rstrip("/")
        self.qwen_key = qwen_cfg.get("api_key") or os.getenv("QWEN_API_KEY", "")
        self.qwen_model = qwen_cfg.get("model") or os.getenv("QWEN_MODEL", "qwen-plus")

        self.minimax_base = (minimax_cfg.get("base_url") or os.getenv("MINIMAX_API_BASE", "")).rstrip("/")
        self.minimax_key = minimax_cfg.get("api_key") or os.getenv("MINIMAX_API_KEY", "")
        self.minimax_model = minimax_cfg.get("model") or os.getenv("MINIMAX_MODEL", "MiniMax-M1")

    def _chat(self, *, base: str, key: str, model: str, system: str, user: str, temperature: float = 0.2) -> str:
        if not base or not key:
            raise RuntimeError("Missing model API configuration")

        url = f"{base}/chat/completions"
        payload_base = {
            "model": model,
            "temperature": temperature,
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
                res = requests.post(url, json=payload, headers=headers, timeout=120)
            except Exception as e:
                errors.append(f"attempt{idx}: network_error={e}")
                continue

            if not res.ok:
                body = (res.text or "")[:300]
                errors.append(f"attempt{idx}: status={res.status_code}, body={body}")
                continue

            try:
                data = res.json()
                return data["choices"][0]["message"]["content"]
            except Exception as e:
                body = (res.text or "")[:300]
                errors.append(f"attempt{idx}: invalid_response={e}, body={body}")

        raise RuntimeError("Model API call failed: " + " | ".join(errors))

    @staticmethod
    def safe_json(text: str) -> dict[str, Any]:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except Exception:
            # Fallback: extract the first JSON object block if model added extra text.
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                return json.loads(m.group(0))
            raise

    def qwen(self, system: str, user: str) -> dict[str, Any]:
        content = self._chat(base=self.qwen_base, key=self.qwen_key, model=self.qwen_model, system=system, user=user)
        return self.safe_json(content)

    def minimax(self, system: str, user: str) -> dict[str, Any]:
        content = self._chat(base=self.minimax_base, key=self.minimax_key, model=self.minimax_model, system=system, user=user)
        return self.safe_json(content)
