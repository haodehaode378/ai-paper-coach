from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.storage import get_paper
from app.core.history_store import (
    CACHE_ROOT,
    UPLOADS_ROOT,
    delete_history_record,
    delete_saved_record,
    list_history_records,
    list_local_files,
    list_saved_records,
    load_history_record,
    load_saved_record,
    save_saved_record,
)

router = APIRouter(tags=["records"])


@router.get("/history")
def history_list():
    return {"items": list_history_records()}


@router.get("/history/{record_id}")
def history_detail(record_id: str):
    record = load_history_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="history record not found")
    return record


@router.delete("/history/{record_id}")
def history_delete(record_id: str):
    ok = delete_history_record(record_id)
    if not ok:
        raise HTTPException(status_code=404, detail="history record not found")
    return {"ok": True, "record_id": record_id}


@router.get("/saved")
def saved_list():
    return {"items": list_saved_records()}


@router.post("/saved/{record_id}")
def save_report(record_id: str):
    record = save_saved_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="history record not found")
    return {"ok": True, "record_id": record_id}


@router.get("/saved/{record_id}")
def saved_detail(record_id: str):
    record = load_saved_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="saved record not found")
    return record


@router.delete("/saved/{record_id}")
def saved_delete(record_id: str):
    ok = delete_saved_record(record_id)
    if not ok:
        raise HTTPException(status_code=404, detail="saved record not found")
    return {"ok": True, "record_id": record_id}


@router.get("/files/uploads")
def uploads_list():
    return {"items": list_local_files("uploads")}


@router.get("/files/cache")
def cache_list():
    return {"items": list_local_files("cache")}


@router.get("/papers/{paper_id}/pdf")
def paper_pdf(paper_id: str):
    paper = get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")

    candidate = None
    local_path = str(paper.get("local_pdf_path") or "").strip()

    current_upload_root = Path(UPLOADS_ROOT)
    current_cache_root = Path(CACHE_ROOT)
    # Backward-compatible root used by older router code.
    legacy_data_root = Path(__file__).resolve().parents[4] / "data"
    legacy_upload_root = legacy_data_root / "uploads"
    legacy_cache_root = legacy_data_root / "cache"

    if local_path:
        path_obj = Path(local_path)
        if path_obj.exists() and path_obj.is_file():
            candidate = path_obj
        else:
            filename = path_obj.name
            for root in (current_upload_root, legacy_upload_root):
                fallback = root / filename
                if fallback.exists() and fallback.is_file():
                    candidate = fallback
                    break

    if candidate is None:
        for root in (current_cache_root, legacy_cache_root):
            cache_path = root / f"{paper_id}.pdf"
            if cache_path.exists() and cache_path.is_file():
                candidate = cache_path
                break

    if candidate is None:
        raise HTTPException(status_code=404, detail="pdf not found")

    return FileResponse(
        path=str(candidate),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"{paper_id}.pdf\""},
    )
