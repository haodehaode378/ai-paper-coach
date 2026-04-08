from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.chunker import split_sections, top_chunks
from app.core.orchestrator import generate_draft, normalize_report, patch_draft, review_draft
from app.core.parser import parse_pdf_file, parse_url
from app.core.schemas import AnalyzeRequest, FinalizeRequest, ReviewRequest
from app.core.storage import (
    create_run,
    get_latest_parse,
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


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    paper = get_paper(req.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")

    run = create_run(paper_id=req.paper_id, mode=req.mode)

    try:
        parse_status, sections, chunks = _parse_paper(paper)
        cfg = req.llm_config.model_dump() if req.llm_config else None
        draft = generate_draft(chunks=chunks, source_type=paper["source_type"], model_config=cfg)
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
        review_data = review_draft(draft=draft, chunks=chunks, model_config=cfg)
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
        final = patch_draft(draft=draft, review=review, strict=req.strict, model_config=cfg)
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

