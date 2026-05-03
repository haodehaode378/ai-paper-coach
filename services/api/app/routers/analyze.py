from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.model_router import ModelRouter
from app.core.pipeline import (
    execute_analyze,
    execute_finalize,
    execute_review,
    create_job,
    get_job,
    stream_events,
    _merge_report_for_display,
    _is_placeholder_title,  # re-exported for tests
)
from app.core.schemas import AnalyzeRequest, FinalizeRequest, PipelineStartRequest, ReviewRequest, ValidateModelsRequest
from app.core.storage import (
    get_latest_run,
    get_llm_traces,
    get_outputs,
    get_paper,
)

router = APIRouter(tags=["pipeline"])


def _validate_one_router(router_client: ModelRouter, slot: str) -> dict[str, Any]:
    start = perf_counter()
    info = router_client.provider_info(slot)
    base = info.get("base_url", "")
    model = info.get("model", "")
    display_name = info.get("name", slot)

    try:
        data = router_client.ping_slot(slot, user="ping")
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
        _validate_one_router(router_client, "primary"),
        _validate_one_router(router_client, "secondary"),
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

    cfg = req.llm_config.model_dump() if req.llm_config else None
    try:
        return execute_analyze(paper_id=req.paper_id, mode=req.mode, model_config=cfg)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"analyze failed: {e}") from e


@router.post("/review")
def review(req: ReviewRequest):
    cfg = req.llm_config.model_dump() if req.llm_config else None
    try:
        return execute_review(paper_id=req.paper_id, model_config=cfg)
    except ValueError as e:
        status = 404 if "no run" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"review failed: {e}") from e


@router.post("/finalize")
def finalize(req: FinalizeRequest):
    cfg = req.llm_config.model_dump() if req.llm_config else None
    try:
        return execute_finalize(paper_id=req.paper_id, strict=req.strict, model_config=cfg)
    except ValueError as e:
        status = 404 if "no run" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"finalize failed: {e}") from e


@router.get("/report/{paper_id}")
def report(paper_id: str):
    run = get_latest_run(paper_id)
    if not run:
        raise HTTPException(status_code=404, detail="no run found")
    outputs = get_outputs(run["id"])

    final = outputs.get("final_json")
    draft = outputs.get("draft_json")
    review_data = outputs.get("review_json")
    if final:
        merged = _merge_report_for_display(draft=draft, review=review_data, final=final)
        if merged:
            return merged
    if draft:
        merged = _merge_report_for_display(draft=draft, review=review_data, final=None)
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


@router.post("/pipeline/start")
async def pipeline_start(req: PipelineStartRequest):
    paper = get_paper(req.paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")

    cfg = req.llm_config.model_dump() if req.llm_config else None
    return await create_job(paper_id=req.paper_id, mode=req.mode, strict=req.strict, llm_config=cfg)


@router.get("/pipeline/jobs/{job_id}")
def pipeline_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="pipeline job not found")
    return job


@router.get("/pipeline/jobs/{job_id}/events")
async def pipeline_job_events(job_id: str):
    return StreamingResponse(
        stream_events(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
