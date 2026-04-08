import json
import os
import time

import requests

BASE = os.getenv("API_BASE", "http://localhost:8000")
PAPER_URL = os.getenv("PAPER_URL", "https://arxiv.org/abs/1706.03762")


def post(path, payload):
    r = requests.post(f"{BASE}{path}", json=payload, timeout=120)
    r.raise_for_status()
    return r.json()


def main():
    ing = post("/ingest", {"url": PAPER_URL})
    paper_id = ing["paper_id"]
    print("paper_id:", paper_id)

    print(post("/analyze", {"paper_id": paper_id, "mode": "deep"}))
    print(post("/review", {"paper_id": paper_id}))
    print(post("/finalize", {"paper_id": paper_id, "strict": False}))

    rep = requests.get(f"{BASE}/report/{paper_id}", timeout=60)
    rep.raise_for_status()
    data = rep.json()
    print(json.dumps(data, ensure_ascii=False, indent=2)[:1200])


if __name__ == "__main__":
    main()
