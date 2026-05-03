from __future__ import annotations

import math
import re
import uuid
from pathlib import Path
from time import perf_counter
from typing import Any

from app.core.model_router import ModelRouter
from app.core.parser import extract_pdf_pages, parse_url
from app.core.storage import get_document_chunks, get_latest_parse, get_paper, replace_document_chunks
from app.core.tracing import traceable_if_enabled

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")
CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]")
STRATEGY = "page-window-v1"


def _clip_text(value: Any, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _is_cjk_query(text: str) -> bool:
    chars = CJK_RE.findall(text)
    return len(chars) >= 3 and len(chars) / max(len(text), 1) > 0.3


def _translate_query_for_retrieval(question: str, *, model_config: dict[str, Any] | None, model_slot: str) -> str:
    if not _is_cjk_query(question):
        return question
    try:
        router = ModelRouter(model_config=model_config, trace_phase="rag-translate")
        translated = router.chat_text(
            slot=model_slot,
            system="You translate search queries. Return ONLY the English translation, nothing else. No quotes, no explanation.",
            user=question,
        )
        translated = translated.strip().strip('"').strip("'")
        return translated if translated and len(translated) > 2 else question
    except Exception:
        return question


def _summarize_chunk(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": item.get("id"),
        "chunk_index": item.get("chunk_index"),
        "page_start": item.get("page_start"),
        "page_end": item.get("page_end"),
        "section": item.get("section"),
        "score": item.get("score"),
        "content_preview": _clip_text(item.get("content"), 500),
    }


def _trace_rag_query_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": inputs.get("paper_id"),
        "question": inputs.get("question"),
        "chunk_size": inputs.get("chunk_size"),
        "chunk_overlap": inputs.get("chunk_overlap"),
        "top_k": inputs.get("top_k"),
        "model_slot": inputs.get("model_slot"),
        "use_llm": inputs.get("use_llm"),
        "has_model_config": isinstance(inputs.get("model_config"), dict),
        "has_fallback_report": isinstance(inputs.get("fallback_report"), dict),
    }


def _trace_rag_query_outputs(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"output_type": type(output).__name__}
    debug = output.get("debug") if isinstance(output.get("debug"), dict) else {}
    citations = output.get("citations") if isinstance(output.get("citations"), list) else []
    return {
        "paper_id": output.get("paper_id"),
        "question": output.get("question"),
        "answer_mode": output.get("answer_mode"),
        "answer_preview": _clip_text(output.get("answer"), 800),
        "citation_count": len(citations),
        "citations": [_summarize_chunk(item) for item in citations[:5] if isinstance(item, dict)],
        "debug": {
            "strategy": debug.get("strategy"),
            "params": debug.get("params"),
            "chunk_count": debug.get("chunk_count"),
            "query_token_count": debug.get("query_token_count"),
            "matched_chunk_count": debug.get("matched_chunk_count"),
            "generation": debug.get("generation"),
            "latency_ms": debug.get("latency_ms"),
        },
    }


def _trace_retrieve_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    chunks = inputs.get("chunks")
    return {
        "question": inputs.get("question"),
        "top_k": inputs.get("top_k"),
        "chunk_count": len(chunks) if isinstance(chunks, list) else 0,
    }


def _trace_retrieve_outputs(output: Any) -> dict[str, Any]:
    hits = output if isinstance(output, list) else []
    return {
        "matched_chunk_count": len(hits),
        "top_chunks": [_summarize_chunk(item) for item in hits[:5] if isinstance(item, dict)],
    }


def _trace_generation_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    hits = inputs.get("hits")
    return {
        "question": inputs.get("question"),
        "hit_count": len(hits) if isinstance(hits, list) else 0,
        "model_slot": inputs.get("model_slot"),
        "use_llm": inputs.get("use_llm"),
        "has_model_config": isinstance(inputs.get("model_config"), dict),
    }


def _trace_generation_outputs(output: Any) -> dict[str, Any]:
    if not isinstance(output, tuple) or len(output) < 3:
        return {"output_type": type(output).__name__}
    answer, answer_mode, debug = output
    return {
        "answer_mode": answer_mode,
        "answer_preview": _clip_text(answer, 800),
        "generation": debug if isinstance(debug, dict) else None,
    }


def _clip_int(value: int, *, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def normalize_rag_params(chunk_size: int = 900, chunk_overlap: int = 120, top_k: int = 5) -> dict[str, int]:
    safe_chunk_size = _clip_int(chunk_size or 900, low=200, high=2400)
    safe_overlap = _clip_int(chunk_overlap or 0, low=0, high=min(600, safe_chunk_size // 2))
    safe_top_k = _clip_int(top_k or 5, low=1, high=12)
    return {"chunk_size": safe_chunk_size, "chunk_overlap": safe_overlap, "top_k": safe_top_k}


def tokenize(text: str) -> list[str]:
    return [item.lower() for item in TOKEN_RE.findall(str(text or ""))]


def _resolve_pdf_pages(paper: dict[str, Any]) -> list[dict[str, Any]]:
    if paper.get("source_type") == "upload":
        local_path = str(paper.get("local_pdf_path") or "").strip()
        if not local_path:
            return []
        path = Path(local_path)
        if not path.exists() or not path.is_file():
            return []
        return extract_pdf_pages(path.read_bytes())

    parsed = parse_url(str(paper.get("source_name") or ""))
    pages = parsed.get("pages")
    return pages if isinstance(pages, list) else []


def _window_text(
    *,
    text: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []

    chunks: list[str] = []
    step = max(chunk_size - chunk_overlap, 1)
    start = 0
    while start < len(normalized):
        content = normalized[start : start + chunk_size].strip()
        if content:
            chunks.append(content)
        if start + chunk_size >= len(normalized):
            break
        start += step
    return chunks


def build_chunks_from_pages(
    paper_id: str,
    pages: list[dict[str, Any]],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page_item in pages:
        page = int(page_item.get("page") or 0)
        if page <= 0:
            continue
        for content in _window_text(
            text=str(page_item.get("text") or ""),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ):
            idx = len(chunks)
            chunks.append(
                {
                    "id": f"{paper_id}:chunk:{idx}:{uuid.uuid4().hex[:8]}",
                    "chunk_index": idx,
                    "page_start": page,
                    "page_end": page,
                    "section": f"page {page}",
                    "content": content,
                    "tokens": tokenize(content),
                }
            )
    return chunks


def build_chunks_from_sections(
    paper_id: str,
    sections: dict[str, Any],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for title, body in sections.items():
        section = str(title or "section").strip() or "section"
        for content in _window_text(
            text=str(body or ""),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ):
            idx = len(chunks)
            chunks.append(
                {
                    "id": f"{paper_id}:section-chunk:{idx}:{uuid.uuid4().hex[:8]}",
                    "chunk_index": idx,
                    "page_start": None,
                    "page_end": None,
                    "section": section,
                    "content": content,
                    "tokens": tokenize(content),
                }
            )
    return chunks


def report_to_sections(report: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(report, dict):
        return {}

    sections: dict[str, str] = {}

    def add_value(prefix: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                sections[prefix] = text
            return
        if isinstance(value, list):
            text = "\n".join(str(item).strip() for item in value if str(item).strip())
            if text:
                sections[prefix] = text
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                add_value(f"{prefix}.{key}", nested)
            return
        text = str(value).strip()
        if text:
            sections[prefix] = text

    for key in ("three_minute_summary", "reproduction_guide", "reading_qa", "teach_classmate", "evidence_refs"):
        add_value(key, report.get(key))
    return sections


def ensure_document_chunks(paper_id: str, *, chunk_size: int, chunk_overlap: int) -> list[dict[str, Any]]:
    cached = get_document_chunks(
        paper_id,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=STRATEGY,
    )
    if cached:
        return cached

    paper = get_paper(paper_id)
    if not paper:
        raise ValueError("paper not found")

    pages = _resolve_pdf_pages(paper)
    chunks = build_chunks_from_pages(
        paper_id,
        pages,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    if not chunks:
        parse_data = get_latest_parse(paper_id)
        section_index = parse_data.get("section_index") if isinstance(parse_data, dict) else None
        if isinstance(section_index, dict):
            chunks = build_chunks_from_sections(
                paper_id,
                section_index,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )

    if chunks:
        replace_document_chunks(
            paper_id,
            chunks,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=STRATEGY,
        )
    return get_document_chunks(
        paper_id,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=STRATEGY,
    )


def _score_chunk(query_tokens: list[str], chunk: dict[str, Any]) -> float:
    if not query_tokens:
        return 0.0
    chunk_tokens = chunk.get("tokens") or tokenize(str(chunk.get("content") or ""))
    if not chunk_tokens:
        return 0.0

    query_set = set(query_tokens)
    chunk_set = set(chunk_tokens)
    overlap = query_set & chunk_set
    if not overlap:
        return 0.0

    tf_score = sum(min(chunk_tokens.count(token), 5) for token in overlap)
    coverage = len(overlap) / max(len(query_set), 1)
    density = tf_score / math.sqrt(max(len(chunk_tokens), 1))
    return round((coverage * 0.7 + density * 0.3) * 100, 4)


@traceable_if_enabled(
    name="rag.retrieve_chunks",
    run_type="retriever",
    metadata={"strategy": STRATEGY},
    process_inputs=_trace_retrieve_inputs,
    process_outputs=_trace_retrieve_outputs,
)
def retrieve_chunks(question: str, chunks: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    query_tokens = tokenize(question)
    scored: list[dict[str, Any]] = []
    for chunk in chunks:
        score = _score_chunk(query_tokens, chunk)
        if score <= 0:
            continue
        scored.append({**chunk, "score": score})

    scored.sort(key=lambda item: (float(item.get("score") or 0), -int(item.get("chunk_index") or 0)), reverse=True)
    return scored[:top_k]


def _citation_label(item: dict[str, Any], index: int) -> str:
    page = item.get("page_start") or item.get("page_end")
    if page:
        return f"[{index}] p.{page}"
    section = str(item.get("section") or "section").strip() or "section"
    return f"[{index}] {section}"


def fallback_answer(question: str, hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "资料中没有检索到足够相关的片段，当前问题建议人工核查原文后再回答。"

    lines = ["根据当前检索到的原文片段，可以先给出以下依据："]
    for idx, item in enumerate(hits[:3], start=1):
        snippet = " ".join(str(item.get("content") or "").split())
        if len(snippet) > 260:
            snippet = snippet[:260].rstrip() + "..."
        lines.append(f"{_citation_label(item, idx)} {snippet}")
    lines.append("这是检索式回答，重点用于展示依据；如需更完整表述，可开启模型生成。")
    return "\n".join(lines)


@traceable_if_enabled(
    name="rag.generate_grounded_answer",
    run_type="chain",
    metadata={"strategy": STRATEGY},
    process_inputs=_trace_generation_inputs,
    process_outputs=_trace_generation_outputs,
)
def generate_grounded_answer(
    *,
    question: str,
    hits: list[dict[str, Any]],
    model_config: dict[str, Any] | None,
    model_slot: str,
    use_llm: bool,
) -> tuple[str, str, dict[str, Any]]:
    if not hits:
        return fallback_answer(question, hits), "fallback", {"requested": bool(use_llm), "used": False, "reason": "no_hits"}
    if not use_llm:
        return fallback_answer(question, hits), "fallback", {"requested": False, "used": False, "reason": "disabled"}

    context = "\n\n".join(
        f"{_citation_label(item, idx)}\n{item.get('content') or ''}"
        for idx, item in enumerate(hits, start=1)
    )
    system = (
        "You answer questions strictly from the provided paper excerpts. "
        "Cite sources with bracket labels like [1] and say clearly when evidence is insufficient. "
        "Answer in the user's language."
    )
    user = f"Question:\n{question}\n\nExcerpts:\n{context}"
    try:
        answer = ModelRouter(model_config=model_config, trace_phase="rag").chat_text(
            slot=model_slot,
            system=system,
            user=user,
        )
        return answer, "llm", {"requested": True, "used": True, "slot": model_slot}
    except Exception as exc:
        return (
            fallback_answer(question, hits),
            "fallback",
            {"requested": True, "used": False, "slot": model_slot, "reason": "llm_error"},
        )


@traceable_if_enabled(
    name="rag.run_rag_query",
    run_type="chain",
    metadata={"strategy": STRATEGY},
    process_inputs=_trace_rag_query_inputs,
    process_outputs=_trace_rag_query_outputs,
)
def run_rag_query(
    *,
    paper_id: str,
    question: str,
    chunk_size: int,
    chunk_overlap: int,
    top_k: int,
    model_config: dict[str, Any] | None = None,
    model_slot: str = "primary",
    use_llm: bool = False,
    fallback_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = normalize_rag_params(chunk_size=chunk_size, chunk_overlap=chunk_overlap, top_k=top_k)
    started = perf_counter()
    chunks = ensure_document_chunks(
        paper_id,
        chunk_size=params["chunk_size"],
        chunk_overlap=params["chunk_overlap"],
    )
    if not chunks and fallback_report:
        chunks = build_chunks_from_sections(
            paper_id,
            report_to_sections(fallback_report),
            chunk_size=params["chunk_size"],
            chunk_overlap=params["chunk_overlap"],
        )
    search_query = _translate_query_for_retrieval(question, model_config=model_config, model_slot=model_slot)
    query_tokens = tokenize(search_query)
    hits = retrieve_chunks(search_query, chunks, top_k=params["top_k"])
    answer, answer_mode, generation_debug = generate_grounded_answer(
        question=question,
        hits=hits,
        model_config=model_config,
        model_slot=model_slot,
        use_llm=use_llm,
    )

    citations = [
        {
            "label": _citation_label(item, idx),
            "chunk_id": item.get("id"),
            "page_start": item.get("page_start"),
            "page_end": item.get("page_end"),
            "section": item.get("section"),
            "score": item.get("score"),
            "content": item.get("content"),
        }
        for idx, item in enumerate(hits, start=1)
    ]
    return {
        "paper_id": paper_id,
        "question": question,
        "answer": answer,
        "answer_mode": answer_mode,
        "citations": citations,
        "debug": {
            "strategy": STRATEGY,
            "params": params,
            "search_query": search_query if search_query != question else None,
            "chunk_count": len(chunks),
            "query_token_count": len(query_tokens),
            "matched_chunk_count": len(hits),
            "top_chunks": citations,
            "generation": generation_debug,
            "latency_ms": int((perf_counter() - started) * 1000),
        },
    }
