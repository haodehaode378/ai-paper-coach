from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.core.orchestrator import to_markdown
from app.core.storage import get_latest_run, get_outputs

router = APIRouter(tags=["export"])


@router.get("/export/{paper_id}.md", response_class=PlainTextResponse)
def export_md(paper_id: str):
    run = get_latest_run(paper_id)
    if not run:
        raise HTTPException(status_code=404, detail="no run found")

    outputs = get_outputs(run["id"])
    report = outputs.get("final_json") or outputs.get("draft_json")
    if not report:
        raise HTTPException(status_code=404, detail="no report available")

    return to_markdown(report)
