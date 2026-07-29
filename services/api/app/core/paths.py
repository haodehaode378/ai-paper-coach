from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DATA_DIR_ENV = "APC_DATA_DIR"
LEGACY_DATA_ROOT = Path(__file__).resolve().parents[3] / "data"
MIGRATION_MARKER = ".legacy-migration-v1.json"
DATA_SUBDIRECTORIES = ("history", "saved", "uploads", "cache", "indexes", "logs")


def resolve_data_root(value: str | None = None) -> Path:
    configured = value if value is not None else os.getenv(DATA_DIR_ENV, "")
    if str(configured or "").strip():
        return Path(str(configured).strip()).expanduser().resolve()
    return LEGACY_DATA_ROOT.resolve()


DATA_ROOT = resolve_data_root()


def ensure_data_directories(root: Path | None = None) -> Path:
    target = (root or DATA_ROOT).resolve()
    target.mkdir(parents=True, exist_ok=True)
    for name in DATA_SUBDIRECTORIES:
        (target / name).mkdir(parents=True, exist_ok=True)
    return target


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def migrate_legacy_data(
    target_root: Path,
    *,
    legacy_root: Path = LEGACY_DATA_ROOT,
) -> dict[str, Any]:
    source = legacy_root.resolve()
    target = target_root.resolve()
    ensure_data_directories(target)

    if source == target:
        return {
            "status": "not_needed",
            "source": str(source),
            "target": str(target),
            "copied_files": 0,
            "skipped_existing": 0,
            "skipped_symlinks": 0,
        }

    marker_path = target / MIGRATION_MARKER
    if marker_path.exists():
        return {
            "status": "already_completed",
            "source": str(source),
            "target": str(target),
            "copied_files": 0,
            "skipped_existing": 0,
            "skipped_symlinks": 0,
        }

    copied_files = 0
    skipped_existing = 0
    skipped_symlinks = 0
    if source.exists() and source.is_dir():
        for source_path in source.rglob("*"):
            if source_path.is_symlink():
                skipped_symlinks += 1
                continue
            relative_path = source_path.relative_to(source)
            target_path = target / relative_path
            if source_path.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            if not source_path.is_file():
                continue
            if target_path.exists():
                skipped_existing += 1
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            copied_files += 1

    result = {
        "status": "completed",
        "source": str(source),
        "target": str(target),
        "copied_files": copied_files,
        "skipped_existing": skipped_existing,
        "skipped_symlinks": skipped_symlinks,
        "completed_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    _write_json_atomic(marker_path, result)
    return result
