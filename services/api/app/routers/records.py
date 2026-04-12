from fastapi import APIRouter, HTTPException

from app.core.history_store import (
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


@router.get("/files/uploads")
def uploads_list():
    return {"items": list_local_files("uploads")}


@router.get("/files/cache")
def cache_list():
    return {"items": list_local_files("cache")}