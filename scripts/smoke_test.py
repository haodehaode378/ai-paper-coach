import json
import os
import time

import requests

BASE = os.getenv("API_BASE", "http://localhost:8000")
PAPER_URL = os.getenv("PAPER_URL", "https://arxiv.org/abs/1706.03762")


def unwrap_envelope(payload):
    if not isinstance(payload, dict):
        return payload
    if not {"success", "data", "error"}.issubset(payload.keys()):
        return payload
    if payload.get("success"):
        return payload.get("data")
    err = payload.get("error") or {}
    code = err.get("code")
    msg = err.get("message") or "request failed"
    raise RuntimeError(f"API failed: code={code}, message={msg}")


def post(path, payload):
    r = requests.post(f"{BASE}{path}", json=payload, timeout=120)
    r.raise_for_status()
    return unwrap_envelope(r.json())


def main():
    ing = post("/ingest", {"url": PAPER_URL})
    paper_id = ing["paper_id"]
    print("paper_id:", paper_id)

    print(post("/analyze", {"paper_id": paper_id, "mode": "deep"}))
    print(post("/review", {"paper_id": paper_id}))
    print(post("/finalize", {"paper_id": paper_id, "strict": False}))

    rep = requests.get(f"{BASE}/report/{paper_id}", timeout=60)
    rep.raise_for_status()
    data = unwrap_envelope(rep.json())
    print(json.dumps(data, ensure_ascii=False, indent=2)[:1200])


if __name__ == "__main__":
    main()
