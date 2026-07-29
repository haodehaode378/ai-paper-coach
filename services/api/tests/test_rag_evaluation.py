from __future__ import annotations

import json
from pathlib import Path

from app.core.rag_evaluation import evaluate_rag_dataset


FIXTURE = Path(__file__).parent / "fixtures" / "rag_eval" / "baseline.json"


def test_lexical_retriever_matches_recorded_baseline():
    dataset = json.loads(FIXTURE.read_text(encoding="utf-8"))

    result = evaluate_rag_dataset(dataset)

    assert result["metrics"] == dataset["expected_baseline"]
    assert result["answerable_count"] == 5
    assert result["no_answer_count"] == 2


def test_baseline_exposes_cross_language_and_stopword_gaps():
    dataset = json.loads(FIXTURE.read_text(encoding="utf-8"))

    result = evaluate_rag_dataset(dataset)
    cases = {item["id"]: item for item in result["cases"]}

    assert cases["cross-language-factual"]["hit_ids"] == []
    assert cases["no-answer-stopword"]["correct_no_answer"] is False
