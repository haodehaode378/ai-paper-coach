from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.rag_evaluation import evaluate_rag_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the current RAG retriever against a deterministic dataset.")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--check-baseline", action="store_true")
    args = parser.parse_args()

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    result = evaluate_rag_dataset(dataset, top_k=args.top_k)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.check_baseline:
        expected = dataset.get("expected_baseline")
        actual = result["metrics"]
        if expected != actual:
            print(
                json.dumps({"baseline_mismatch": {"expected": expected, "actual": actual}}, ensure_ascii=False, indent=2),
                file=sys.stderr,
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
