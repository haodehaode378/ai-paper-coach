from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.chunker import split_sections, top_chunks
from app.core.model_router import ModelRouter
from app.core.orchestrator import generate_draft, get_requirement_issues, normalize_report, patch_draft, review_draft
from app.core.history_store import CACHE_ROOT as HISTORY_CACHE_ROOT, list_history_records, load_history_record, save_history_record
from app.core.parser import parse_pdf_file, parse_url
from app.core.schemas import AnalyzeRequest, FinalizeRequest, PipelineStartRequest, ReviewRequest, ValidateModelsRequest
from app.core.storage import (
    append_llm_trace,
    create_run,
    get_latest_parse,
    get_llm_traces,
    get_latest_run,
    get_outputs,
    get_paper,
    get_pipeline_job,
    save_draft,
    save_final,
    save_parse,
    save_pipeline_job,
    save_review,
    update_run_status,
    now_iso,
)

router = APIRouter(tags=["pipeline"])

CACHE_ROOT = Path(HISTORY_CACHE_ROOT)
CACHE_ROOT.mkdir(parents=True, exist_ok=True)

PIPELINE_JOBS: dict[str, dict[str, Any]] = {}
PIPELINE_JOBS_LOCK = threading.Lock()
PIPELINE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline-job")


def _new_job_payload(*, job_id: str, paper_id: str, mode: str, strict: bool) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "paper_id": paper_id,
        "mode": mode,
        "strict": strict,
        "status": "running",
        "current_stage": "pending",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "error": None,
        "result": None,
        "events": [],
        "next_event_id": 1,
    }


def _append_job_event(job: dict[str, Any], *, event_type: str, stage: str | None = None, message: str | None = None, data: Any = None) -> None:
    event = {
        "id": job["next_event_id"],
        "type": event_type,
        "stage": stage,
        "message": message,
        "data": data,
        "ts": now_iso(),
    }
    job["next_event_id"] += 1
    job["events"].append(event)
    if len(job["events"]) > 500:
        job["events"] = job["events"][-500:]
    job["updated_at"] = now_iso()


def _job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job["job_id"],
        "paper_id": job["paper_id"],
        "mode": job["mode"],
        "strict": job["strict"],
        "status": job["status"],
        "current_stage": job["current_stage"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "error": job["error"],
        "result": job["result"],
        "events": list(job["events"]),
    }


def _persist_job(job: dict[str, Any]) -> None:
    save_pipeline_job(job)


def _run_pipeline_job(job_id: str, req: PipelineStartRequest) -> None:
    with PIPELINE_JOBS_LOCK:
        job = PIPELINE_JOBS.get(job_id)
    if not job:
        job = get_pipeline_job(job_id)
        if not job:
            return
        with PIPELINE_JOBS_LOCK:
            PIPELINE_JOBS[job_id] = job

    try:
        with PIPELINE_JOBS_LOCK:
            job["current_stage"] = "analyze"
            _append_job_event(job, event_type="stage_started", stage="analyze", message="\u5f00\u59cb\u6267\u884c\u5206\u6790\u9636\u6bb5")
            _persist_job(job)

        analyze_result = analyze(AnalyzeRequest(paper_id=req.paper_id, mode=req.mode, model_config=req.llm_config))

        with PIPELINE_JOBS_LOCK:
            _append_job_event(job, event_type="stage_completed", stage="analyze", data=analyze_result)
            _persist_job(job)

        if req.mode != "fast":
            with PIPELINE_JOBS_LOCK:
                job["current_stage"] = "review"
                _append_job_event(job, event_type="stage_started", stage="review", message="\u5f00\u59cb\u6267\u884c\u5ba1\u9605\u9636\u6bb5")
                _persist_job(job)

            review_result = review(ReviewRequest(paper_id=req.paper_id, model_config=req.llm_config))

            with PIPELINE_JOBS_LOCK:
                _append_job_event(job, event_type="stage_completed", stage="review", data=review_result)
                _persist_job(job)

            with PIPELINE_JOBS_LOCK:
                job["current_stage"] = "finalize"
                _append_job_event(job, event_type="stage_started", stage="finalize", message="\u5f00\u59cb\u6267\u884c\u6574\u7406\u9636\u6bb5")
                _persist_job(job)

            finalize_result = finalize(FinalizeRequest(paper_id=req.paper_id, strict=req.strict or req.mode == "strict", model_config=req.llm_config))

            with PIPELINE_JOBS_LOCK:
                _append_job_event(job, event_type="stage_completed", stage="finalize", data=finalize_result)
                _persist_job(job)

        run = get_latest_run(req.paper_id)
        with PIPELINE_JOBS_LOCK:
            job["status"] = "completed"
            job["current_stage"] = "done"
            job["result"] = {
                "paper_id": req.paper_id,
                "run_id": (run or {}).get("id"),
            }
            _append_job_event(job, event_type="completed", stage="done", data=job["result"])
            _persist_job(job)
    except Exception as exc:
        with PIPELINE_JOBS_LOCK:
            job["status"] = "failed"
            job["error"] = str(exc)
            _append_job_event(job, event_type="failed", stage=job.get("current_stage"), message=str(exc))
            _persist_job(job)


def _merge_report_for_display(
    *,
    draft: dict[str, Any] | None = None,
    review: dict[str, Any] | None = None,
    final: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    base = final or draft
    if not isinstance(base, dict):
        return None

    source_type = (base.get("paper_meta") or {}).get("source_type", "url") if isinstance(base, dict) else "url"
    merged = normalize_report(base, source_type=source_type)

    if isinstance(review, dict):
        review_qa = (review.get("reading_qa") or {}) if isinstance(review.get("reading_qa"), dict) else {}
        merged["reading_qa"] = {
            **merged.get("reading_qa", {}),
            **{k: v for k, v in review_qa.items() if str(v or "").strip()},
        }
        merged["evidence_refs"] = list(merged.get("evidence_refs", [])) + list(review.get("evidence_refs", []) or [])
        merged["change_log"] = list(merged.get("change_log", [])) + list(review.get("change_log", []) or [])

    return normalize_report(merged, source_type=source_type)


def _parse_paper(paper: dict[str, Any], mode: str = "deep") -> tuple[str, dict[str, str], list[dict[str, str]]]:
    if paper.get("source_type") == "upload":
        parsed = parse_pdf_file(paper["local_pdf_path"])
    else:
        cache_path = CACHE_ROOT / f"{paper['id']}.pdf"
        parsed = parse_url(paper["source_name"], download_to=str(cache_path))

    text = parsed.get("text", "") or ""
    status = parsed.get("status", "failed")
    sections = split_sections(text)
    if mode == "full":
        chunks = [{"section": title, "content": content} for title, content in sections.items() if content.strip()]
    else:
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


def _json_len(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        return len(str(value))




def _is_placeholder_title(value: Any) -> bool:
    title_raw = str(value or "").strip()
    title = title_raw.lower().replace("_", " ")
    if not title:
        return True
    normalized = " ".join(title.split())
    if normalized in {
        "unknown title",
        "unknowntitle",
        "untitled",
        "no title",
        "not provided",
        "not available",
        "?????",
        "????",
        "-",
    }:
        return True
    # Common placeholder titles generated in Chinese fallback flows.
    if title_raw.startswith("论文中未明确说明"):
        return True
    if "未明确说明" in title_raw and len(title_raw) <= 24:
        return True
    if "not explicitly stated" in normalized:
        return True
    return False



def _maybe_backfill_paper_title(paper_id: str, report: dict[str, Any] | None, paper: dict[str, Any] | None) -> None:
    report_title = ((report or {}).get("paper_meta") or {}).get("title")
    current_title = (paper or {}).get("title")
    fallback_title = (paper or {}).get("source_name") or paper_id

    candidate = None
    if not _is_placeholder_title(report_title):
        candidate = str(report_title).strip()
    elif not _is_placeholder_title(current_title):
        candidate = str(current_title).strip()
    elif fallback_title:
        candidate = str(fallback_title).strip()

    if not candidate:
        return

    from app.core.storage import get_conn

    with get_conn() as conn:
        conn.execute("UPDATE papers SET title = ? WHERE id = ?", (candidate, paper_id))

def _save_history_snapshot(*, run: dict[str, Any], paper: dict[str, Any], report: dict[str, Any], stage: str) -> None:
    payload = {
        "record_id": run["id"],
        "run_id": run["id"],
        "paper_id": paper["id"],
        "stage": stage,
        "status": run.get("status", "done"),
        "saved_at": run.get("finished_at") or run.get("started_at"),
        "meta": {
            "paper_id": paper["id"],
            "title": (
                paper.get("source_name") if _is_placeholder_title((report.get("paper_meta") or {}).get("title"))
                else (report.get("paper_meta") or {}).get("title")
            ) or paper.get("title") or paper.get("source_name") or paper["id"],
            "source_type": paper.get("source_type", "url"),
            "source_name": paper.get("source_name", "-"),
            "saved_at": run.get("finished_at") or run.get("started_at"),
        },
        "report": report,
    }
    save_history_record(record_id=run["id"], payload=payload)


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

    stage_start = perf_counter()
    try:
        parse_status, sections, chunks = _parse_paper(paper, req.mode)
        cfg = req.llm_config.model_dump() if req.llm_config else None
        draft = generate_draft(
            chunks=chunks,
            source_type=paper["source_type"],
            model_config=cfg,
            trace_hook=lambda item: append_llm_trace(run_id=run["id"], **item),
        )
        save_draft(run["id"], draft)
        update_run_status(run["id"], "done")
        run = get_latest_run(req.paper_id) or run
        merged_report = _merge_report_for_display(draft=draft, review=None, final=None)
        if merged_report:
            _maybe_backfill_paper_title(req.paper_id, merged_report, paper)
            _save_history_snapshot(run=run, paper=paper, report=merged_report, stage="analyze")
    except Exception as e:
        update_run_status(run["id"], "failed")
        raise HTTPException(status_code=500, detail=f"analyze failed: {e}") from e

    input_chars = _json_len({"chunks": chunks, "source_type": paper.get("source_type", "url")})
    output_chars = _json_len(draft)
    elapsed_ms = int((perf_counter() - stage_start) * 1000)
    stage_metrics = {
        "stage": "analyze",
        "input_chars": input_chars,
        "output_chars": output_chars,
        "elapsed_ms": elapsed_ms,
    }

    warnings: list[str] = []
    if chunks:
        section_names = [str(item.get("section", "")) for item in chunks if str(item.get("section", "")).strip()]
        total_chars = sum(len(str(item.get("content", ""))) for item in chunks)
        warnings.append(
            f"chunk_selection: sections={len(section_names)} total_chars={total_chars} names={section_names}"
        )
    warnings.append(
        f"stage_metric: analyze input_chars={input_chars} output_chars={output_chars} elapsed_ms={elapsed_ms}"
    )
    if parse_status in {"failed", "summary_only"}:
        warnings.append(f"parse_status={parse_status}")
    if isinstance(draft, dict):
        for line in draft.get("change_log", []):
            if isinstance(line, str) and "模型调用失败" in line:
                warnings.append(line)
        issues = get_requirement_issues(draft)
        if issues:
            warnings.append(
                f"report_requirement: analyze draft has {len(issues)} unresolved requirement issues"
            )

    return {
        "run_id": run["id"],
        "paper_id": req.paper_id,
        "parse_status": parse_status,
        "warnings": warnings,
        "stage_metrics": stage_metrics,
    }


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

    stage_start = perf_counter()
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

    input_chars = _json_len({"draft": draft, "chunks": chunks})
    output_chars = _json_len(review_data)
    elapsed_ms = int((perf_counter() - stage_start) * 1000)
    stage_metrics = {
        "stage": "review",
        "input_chars": input_chars,
        "output_chars": output_chars,
        "elapsed_ms": elapsed_ms,
    }
    warnings = [
        f"stage_metric: review input_chars={input_chars} output_chars={output_chars} elapsed_ms={elapsed_ms}"
    ]

    return {
        "run_id": run["id"],
        "paper_id": req.paper_id,
        "reviewed": True,
        "warnings": warnings,
        "stage_metrics": stage_metrics,
    }


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

    parse_data = get_latest_parse(req.paper_id)
    section_index = parse_data["section_index"] if parse_data else {}
    chunks = top_chunks(section_index) if section_index else []
    finalize_context = {
        "section_index": section_index,
        "chunks": chunks,
    }

    stage_start = perf_counter()
    try:
        cfg = req.llm_config.model_dump() if req.llm_config else None
        final = patch_draft(
            draft=draft,
            review=review,
            context=finalize_context,
            strict=req.strict,
            model_config=cfg,
            trace_hook=lambda item: append_llm_trace(run_id=run["id"], **item),
        )
        save_final(run["id"], final)
        run = get_latest_run(req.paper_id) or run
        paper = get_paper(req.paper_id)
        merged_report = _merge_report_for_display(draft=draft, review=review, final=final)
        if paper and merged_report:
            _maybe_backfill_paper_title(req.paper_id, merged_report, paper)
            _save_history_snapshot(run=run, paper=paper, report=merged_report, stage="finalize")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"finalize failed: {e}") from e

    input_chars = _json_len({"draft": draft, "review": review, "context": finalize_context, "strict": req.strict})
    output_chars = _json_len(final)
    elapsed_ms = int((perf_counter() - stage_start) * 1000)
    stage_metrics = {
        "stage": "finalize",
        "input_chars": input_chars,
        "output_chars": output_chars,
        "elapsed_ms": elapsed_ms,
    }
    warnings = [
        f"stage_metric: finalize input_chars={input_chars} output_chars={output_chars} elapsed_ms={elapsed_ms}"
    ]

    return {
        "run_id": run["id"],
        "paper_id": req.paper_id,
        "finalized": True,
        "warnings": warnings,
        "stage_metrics": stage_metrics,
    }


@router.get("/report/{paper_id}")
def report(paper_id: str):
    run = get_latest_run(paper_id)
    if not run:
        raise HTTPException(status_code=404, detail="no run found")
    outputs = get_outputs(run["id"])

    final = outputs.get("final_json")
    draft = outputs.get("draft_json")
    review = outputs.get("review_json")
    if final:
        merged = _merge_report_for_display(draft=draft, review=review, final=final)
        if merged:
            return merged
    if draft:
        merged = _merge_report_for_display(draft=draft, review=review, final=None)
        if merged:
            return merged
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

@router.get("/history")
def history_list():
    return {
        "items": list_history_records(),
    }


@router.get("/history/{record_id}")
def history_detail(record_id: str):
    record = load_history_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="history record not found")
    return record

@router.post("/pipeline/start")
def pipeline_start(req: PipelineStartRequest):
    paper = get_paper(req.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")

    job_id = str(uuid.uuid4())
    job = _new_job_payload(job_id=job_id, paper_id=req.paper_id, mode=req.mode, strict=req.strict)
    with PIPELINE_JOBS_LOCK:
        PIPELINE_JOBS[job_id] = job
        _append_job_event(job, event_type="queued", stage="pending", message="\u4efb\u52a1\u5df2\u5165\u961f\uff0c\u7b49\u5f85\u540e\u53f0\u6267\u884c")

    PIPELINE_EXECUTOR.submit(_run_pipeline_job, job_id, req)
    return {
        "job_id": job_id,
        "status": "running",
        "paper_id": req.paper_id,
        "mode": req.mode,
    }


@router.get("/pipeline/jobs/{job_id}")
def pipeline_job_status(job_id: str):
    with PIPELINE_JOBS_LOCK:
        job = PIPELINE_JOBS.get(job_id)
    if not job:
        job = get_pipeline_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="pipeline job not found")
        with PIPELINE_JOBS_LOCK:
            PIPELINE_JOBS[job_id] = job
    return _job_snapshot(job)


@router.get("/pipeline/jobs/{job_id}/events")
def pipeline_job_events(job_id: str):
    def event_stream():
        cursor = 0
        while True:
            with PIPELINE_JOBS_LOCK:
                job = PIPELINE_JOBS.get(job_id)

            if not job:
                job = get_pipeline_job(job_id)
                if not job:
                    payload = {"type": "failed", "message": "pipeline job not found", "ts": now_iso()}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break
                with PIPELINE_JOBS_LOCK:
                    PIPELINE_JOBS[job_id] = job

            events = list(job["events"])
            status = job["status"]

            while cursor < len(events):
                payload = events[cursor]
                cursor += 1
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            if status in {"completed", "failed"}:
                yield "data: [DONE]\n\n"
                break

            time.sleep(0.7)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
