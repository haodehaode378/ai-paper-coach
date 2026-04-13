from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.core.storage import create_paper
from app.core.history_store import UPLOADS_ROOT

router = APIRouter(tags=["ingest"])

UPLOAD_ROOT = Path(UPLOADS_ROOT)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


@router.post("/ingest")
async def ingest(request: Request, file: UploadFile | None = File(default=None), url: str | None = Form(default=None)):
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        payload = await request.json()
        input_url = (payload or {}).get("url")
        if not input_url:
            raise HTTPException(status_code=400, detail="url is required for JSON ingest")
        paper = create_paper(source_type="url", source_name=input_url)
        return {"paper_id": paper["id"], "source_type": "url"}

    if file is None and not url:
        raise HTTPException(status_code=400, detail="Provide file upload or url")

    if file is not None:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported in MVP")

        tmp_paper = create_paper(source_type="upload", source_name=file.filename)
        save_path = UPLOAD_ROOT / f"{tmp_paper['id']}.pdf"
        data = await file.read()
        save_path.write_bytes(data)

        # Update paper with local path by recreating entry not needed; use source_name + path via create_paper API now.
        # For simplicity in MVP, create fresh paper with path and return the latest valid one.
        from app.core.storage import get_conn

        with get_conn() as conn:
            conn.execute("UPDATE papers SET local_pdf_path = ? WHERE id = ?", (str(save_path), tmp_paper["id"]))

        return {"paper_id": tmp_paper["id"], "source_type": "upload", "filename": file.filename}

    paper = create_paper(source_type="url", source_name=url)
    return {"paper_id": paper["id"], "source_type": "url"}
