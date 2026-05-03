from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    try:
        from PyPDF2 import PdfReader  # type: ignore[assignment]
    except Exception:  # pragma: no cover
        PdfReader = None

from app.core.storage import create_paper
from app.core.parser import infer_title_from_source
from app.core.history_store import UPLOADS_ROOT

router = APIRouter(tags=["ingest"])

UPLOAD_ROOT = Path(UPLOADS_ROOT)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def _max_upload_bytes() -> int:
    raw = (os.getenv("APC_MAX_UPLOAD_MB", "20") or "20").strip()
    try:
        mb = float(raw)
    except Exception:
        mb = 20.0
    if mb <= 0:
        mb = 20.0
    return int(mb * 1024 * 1024)


@router.post("/ingest")
async def ingest(request: Request, file: UploadFile | None = File(default=None), url: str | None = Form(default=None)):
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        payload = await request.json()
        input_url = (payload or {}).get("url")
        if not input_url:
            raise HTTPException(status_code=400, detail="url is required for JSON ingest")
        paper = create_paper(source_type="url", source_name=input_url, title=infer_title_from_source("url", input_url))
        return {"paper_id": paper["id"], "source_type": "url"}

    if file is None and not url:
        raise HTTPException(status_code=400, detail="Provide file upload or url")

    if file is not None:
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported in MVP")

        tmp_paper = create_paper(source_type="upload", source_name=file.filename, title=infer_title_from_source("upload", file.filename))
        save_path = UPLOAD_ROOT / f"{tmp_paper['id']}.pdf"
        data = await file.read()
        max_bytes = _max_upload_bytes()
        if len(data) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Uploaded file too large (limit={max_bytes // (1024 * 1024)}MB)",
            )
        if not data.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF (invalid header)")
        if PdfReader is None:
            raise HTTPException(status_code=500, detail="PDF dependency missing: install pypdf or PyPDF2")
        try:
            reader = PdfReader(BytesIO(data))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Uploaded file is not a readable PDF: {exc}") from exc
        if reader.is_encrypted:
            raise HTTPException(status_code=400, detail="Encrypted PDF is not supported")
        save_path.write_bytes(data)

        # Update paper with local path by recreating entry not needed; use source_name + path via create_paper API now.
        # For simplicity in MVP, create fresh paper with path and return the latest valid one.
        from app.core.storage import get_conn

        with get_conn() as conn:
            conn.execute("UPDATE papers SET local_pdf_path = ? WHERE id = ?", (str(save_path), tmp_paper["id"]))

        return {"paper_id": tmp_paper["id"], "source_type": "upload", "filename": file.filename}

    paper = create_paper(source_type="url", source_name=url, title=infer_title_from_source("url", url))
    return {"paper_id": paper["id"], "source_type": "url"}
