from __future__ import annotations

from typing import Any

from app.core.rag import retrieve_chunks, tokenize


def evaluate_rag_dataset(dataset: dict[str, Any], *, top_k: int | None = None) -> dict[str, Any]:
    documents = {
        str(item["id"]): item
        for item in dataset.get("documents", [])
        if isinstance(item, dict) and item.get("id")
    }
    cases = [item for item in dataset.get("cases", []) if isinstance(item, dict)]
    default_top_k = int(top_k or dataset.get("top_k") or 5)

    answerable_recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    no_answer_results: list[bool] = []
    case_results: list[dict[str, Any]] = []

    for case in cases:
        document_id = str(case.get("document_id") or "")
        document = documents.get(document_id)
        if not document:
            raise ValueError(f"unknown document_id: {document_id}")

        chunks: list[dict[str, Any]] = []
        for index, item in enumerate(document.get("chunks", [])):
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "")
            chunks.append(
                {
                    **item,
                    "id": str(item.get("id") or f"{document_id}:{index}"),
                    "chunk_index": int(item.get("chunk_index", index)),
                    "content": content,
                    "tokens": item.get("tokens") or tokenize(content),
                }
            )

        question = str(case.get("question") or "")
        hits = retrieve_chunks(question, chunks, top_k=default_top_k)
        hit_ids = [str(item.get("id") or "") for item in hits]
        expected_ids = {str(item) for item in case.get("relevant_chunk_ids", [])}
        expects_no_answer = bool(case.get("expect_no_answer"))

        recall: float | None = None
        reciprocal_rank: float | None = None
        correct_no_answer: bool | None = None
        if expects_no_answer:
            correct_no_answer = not hit_ids
            no_answer_results.append(correct_no_answer)
        else:
            if not expected_ids:
                raise ValueError(f"answerable case has no relevant_chunk_ids: {case.get('id')}")
            matched = expected_ids.intersection(hit_ids)
            recall = len(matched) / len(expected_ids)
            answerable_recalls.append(recall)
            reciprocal_rank = 0.0
            for rank, hit_id in enumerate(hit_ids, start=1):
                if hit_id in expected_ids:
                    reciprocal_rank = 1.0 / rank
                    break
            reciprocal_ranks.append(reciprocal_rank)

        case_results.append(
            {
                "id": case.get("id"),
                "document_id": document_id,
                "question": question,
                "expect_no_answer": expects_no_answer,
                "expected_chunk_ids": sorted(expected_ids),
                "hit_ids": hit_ids,
                "recall_at_k": recall,
                "reciprocal_rank": reciprocal_rank,
                "correct_no_answer": correct_no_answer,
            }
        )

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    return {
        "dataset_version": dataset.get("version"),
        "retriever": "lexical",
        "top_k": default_top_k,
        "case_count": len(case_results),
        "answerable_count": len(answerable_recalls),
        "no_answer_count": len(no_answer_results),
        "metrics": {
            "recall_at_k": mean(answerable_recalls),
            "mrr_at_k": mean(reciprocal_ranks),
            "no_answer_accuracy": mean([1.0 if item else 0.0 for item in no_answer_results]),
        },
        "cases": case_results,
    }
