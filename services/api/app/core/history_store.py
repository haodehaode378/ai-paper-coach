from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_ROOT = Path(__file__).resolve().parents[3] / "data"
HISTORY_ROOT = DATA_ROOT / "history"
SAVED_ROOT = DATA_ROOT / "saved"
UPLOADS_ROOT = DATA_ROOT / "uploads"
CACHE_ROOT = DATA_ROOT / "cache"

for root in (HISTORY_ROOT, SAVED_ROOT, UPLOADS_ROOT, CACHE_ROOT):
    root.mkdir(parents=True, exist_ok=True)


def _json_path(root: Path, record_id: str) -> Path:
    return root / f"{record_id}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_history_record(*, record_id: str, payload: dict[str, Any]) -> str:
    path = _json_path(HISTORY_ROOT, record_id)
    _write_json(path, payload)
    return str(path)


def load_history_record(record_id: str) -> dict[str, Any] | None:
    return _read_json(_json_path(HISTORY_ROOT, record_id))


def _summary_from_payload(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta") or {}
    return {
        "record_id": payload.get("record_id") or path.stem,
        "run_id": payload.get("run_id") or path.stem,
        "paper_id": payload.get("paper_id") or meta.get("paper_id"),
        "title": meta.get("title") or payload.get("title") or path.stem,
        "source_type": meta.get("source_type") or "unknown",
        "source_name": meta.get("source_name") or "-",
        "stage": payload.get("stage") or "unknown",
        "status": payload.get("status") or "ready",
        "saved_at": payload.get("saved_at") or meta.get("saved_at") or "",
    }


def _list_json_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        records.append(_summary_from_payload(path, payload))
    return records


def list_history_records() -> list[dict[str, Any]]:
    return _list_json_records(HISTORY_ROOT)


def save_saved_record(record_id: str) -> dict[str, Any] | None:
    payload = load_history_record(record_id)
    if not payload:
        return None
    _write_json(_json_path(SAVED_ROOT, record_id), payload)
    return payload


def load_saved_record(record_id: str) -> dict[str, Any] | None:
    return _read_json(_json_path(SAVED_ROOT, record_id))


def list_saved_records() -> list[dict[str, Any]]:
    return _list_json_records(SAVED_ROOT)


def list_local_files(kind: str) -> list[dict[str, Any]]:
    root = UPLOADS_ROOT if kind == "uploads" else CACHE_ROOT
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        stat = path.stat()
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
                "kind": kind,
            }
        )
    return items

def _delete_json_record(root: Path, record_id: str) -> bool:
    path = _json_path(root, record_id)
    if not path.exists() or not path.is_file():
        return False
    path.unlink()
    return True


def delete_history_record(record_id: str) -> bool:
    return _delete_json_record(HISTORY_ROOT, record_id)


def delete_saved_record(record_id: str) -> bool:
    return _delete_json_record(SAVED_ROOT, record_id)
