from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.chunker import split_sections, top_chunks
from app.core.model_router import ModelRouter
from app.core.orchestrator import generate_draft, get_requirement_issues, normalize_report, patch_draft, review_draft
from app.core.parser import parse_pdf_file, parse_url
from app.core.schemas import AnalyzeRequest, FinalizeRequest, ReviewRequest, ValidateModelsRequest
from app.core.storage import (
    append_llm_trace,
    create_run,
    get_latest_parse,
    get_llm_traces,
    get_latest_run,
    get_outputs,
    get_paper,
    save_draft,
    save_final,
    save_parse,
    save_review,
    update_run_status,
)

router = APIRouter(tags=["pipeline"])

CACHE_ROOT = Path(__file__).resolve().parents[4] / "data" / "cache"
CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def _parse_paper(paper: dict[str, Any]) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    if paper.get("source_type") == "upload":
        parsed = parse_pdf_file(paper["local_pdf_path"])
    else:
        cache_path = CACHE_ROOT / f"{paper['id']}.pdf"
        parsed = parse_url(paper["source_name"], download_to=str(cache_path))

    text = parsed.get("text", "") or ""
    status = parsed.get("status", "failed")
    sections = split_sections(text)
    chunks = top_chunks(sections)

    if not text.strip():
        chunks = [{"section": "ABSTRACT", "content": "No full text extracted. Use summary mode."}]

    save_parse(paper_id=paper["id"], parse_status=status, section_index=sections)
    return status, sections, chunks


def _validate_one_provider(router: ModelRouter, slot: str) -> dict[str, Any]:
    start = perf_counter()
    info = router.provider_info(slot)
    base = info.get("base_url", "")
    model = info.get("model", "")
    display_name = info.get("name", slot)

    try:
        data = router.ping_slot(slot, user="ping")
        latency_ms = int((perf_counter() - start) * 1000)
        return {
            "provider": slot,
            "display_name": display_name,
            "ok": True,
            "latency_ms": latency_ms,
            "base_url": base,
            "model": model,
            "response_preview": data[:120],
        }
    except Exception as e:
        latency_ms = int((perf_counter() - start) * 1000)
        return {
            "provider": slot,
            "display_name": display_name,
            "ok": False,
            "latency_ms": latency_ms,
            "base_url": base,
            "model": model,
            "error": str(e)[:800],
        }


@router.post("/validate-models")
def validate_models(req: ValidateModelsRequest):
    cfg = req.llm_config.model_dump() if req.llm_config else None
    router_client = ModelRouter(model_config=cfg, trace_phase="validate")

    results = [
        _validate_one_provider(router_client, "primary"),
        _validate_one_provider(router_client, "secondary"),
    ]

    return {
        "ok": all(item.get("ok") for item in results),
        "results": results,
    }


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    paper = get_paper(req.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")

    run = create_run(paper_id=req.paper_id, mode=req.mode)

    try:
        parse_status, sections, chunks = _parse_paper(paper)
        cfg = req.llm_config.model_dump() if req.llm_config else None
        draft = generate_draft(
            chunks=chunks,
            source_type=paper["source_type"],
            model_config=cfg,
            trace_hook=lambda item: append_llm_trace(run_id=run["id"], **item),
        )
        save_draft(run["id"], draft)
        update_run_status(run["id"], "done")
    except Exception as e:
        update_run_status(run["id"], "failed")
        raise HTTPException(status_code=500, detail=f"analyze failed: {e}") from e

    warnings: list[str] = []
    if parse_status in {"failed", "summary_only"}:
        warnings.append(f"parse_status={parse_status}")
    if isinstance(draft, dict):
        for line in draft.get("change_log", []):
            if isinstance(line, str) and "模型调用失败" in line:
                warnings.append(line)
        for issue in get_requirement_issues(draft):
            warnings.append(f"report_requirement: {issue}")
    return {"run_id": run["id"], "paper_id": req.paper_id, "parse_status": parse_status, "warnings": warnings}


@router.post("/review")
def review(req: ReviewRequest):
    run = get_latest_run(req.paper_id)
    if not run:
        raise HTTPException(status_code=404, detail="no run found")

    outputs = get_outputs(run["id"])
    draft = outputs.get("draft_json")
    if not draft:
        raise HTTPException(status_code=400, detail="draft not found, call /analyze first")

    parse_data = get_latest_parse(req.paper_id)
    chunks = top_chunks(parse_data["section_index"]) if parse_data else []

    try:
        cfg = req.llm_config.model_dump() if req.llm_config else None
        review_data = review_draft(
            draft=draft,
            chunks=chunks,
            model_config=cfg,
            trace_hook=lambda item: append_llm_trace(run_id=run["id"], **item),
        )
        save_review(run["id"], review_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"review failed: {e}") from e

    return {"run_id": run["id"], "paper_id": req.paper_id, "reviewed": True}


@router.post("/finalize")
def finalize(req: FinalizeRequest):
    run = get_latest_run(req.paper_id)
    if not run:
        raise HTTPException(status_code=404, detail="no run found")

    outputs = get_outputs(run["id"])
    draft = outputs.get("draft_json")
    review = outputs.get("review_json") or {"patch_suggestions": [], "risky_claims": []}
    if not draft:
        raise HTTPException(status_code=400, detail="draft not found")

    try:
        cfg = req.llm_config.model_dump() if req.llm_config else None
        final = patch_draft(
            draft=draft,
            review=review,
            strict=req.strict,
            model_config=cfg,
            trace_hook=lambda item: append_llm_trace(run_id=run["id"], **item),
        )
        save_final(run["id"], final)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"finalize failed: {e}") from e

    return {"run_id": run["id"], "paper_id": req.paper_id, "finalized": True}


@router.get("/report/{paper_id}")
def report(paper_id: str):
    run = get_latest_run(paper_id)
    if not run:
        raise HTTPException(status_code=404, detail="no run found")
    outputs = get_outputs(run["id"])

    final = outputs.get("final_json")
    draft = outputs.get("draft_json")
    if final:
        source_type = (final.get("paper_meta") or {}).get("source_type", "url") if isinstance(final, dict) else "url"
        return normalize_report(final, source_type=source_type)
    if draft:
        source_type = (draft.get("paper_meta") or {}).get("source_type", "url") if isinstance(draft, dict) else "url"
        return normalize_report(draft, source_type=source_type)
    raise HTTPException(status_code=404, detail="no report data")


@router.get("/trace/{paper_id}")
def trace(paper_id: str):
    run = get_latest_run(paper_id)
    if not run:
        return {
            "run_id": None,
            "status": "idle",
            "traces": [],
        }
    return {
        "run_id": run["id"],
        "status": run["status"],
        "traces": get_llm_traces(run["id"]),
    }

