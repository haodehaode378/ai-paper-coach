from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from app.core.paths import MIGRATION_MARKER, migrate_legacy_data, resolve_data_root


def test_resolve_data_root_prefers_explicit_value(tmp_path: Path):
    configured = tmp_path / "desktop data"

    assert resolve_data_root(str(configured)) == configured.resolve()


def test_api_modules_use_configured_data_root_in_fresh_process(tmp_path: Path):
    configured = tmp_path / "desktop data"
    environment = os.environ.copy()
    environment["APC_DATA_DIR"] = str(configured)
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.core.history_store import DATA_ROOT, UPLOADS_ROOT;"
                "from app.core.storage import DB_PATH;"
                "print(DATA_ROOT); print(UPLOADS_ROOT); print(DB_PATH)"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert process.stdout.splitlines() == [
        str(configured.resolve()),
        str(configured.resolve() / "uploads"),
        str(configured.resolve() / "app.db"),
    ]


def test_migrate_legacy_data_copies_without_deleting_source(tmp_path: Path):
    legacy = tmp_path / "legacy"
    target = tmp_path / "desktop"
    history_file = legacy / "history" / "record.json"
    database_file = legacy / "app.db"
    history_file.parent.mkdir(parents=True)
    history_file.write_text('{"title": "demo"}', encoding="utf-8")
    database_file.write_bytes(b"sqlite-placeholder")

    result = migrate_legacy_data(target, legacy_root=legacy)

    assert result["status"] == "completed"
    assert result["copied_files"] == 2
    assert history_file.exists()
    assert database_file.exists()
    assert (target / "history" / "record.json").read_text(encoding="utf-8") == '{"title": "demo"}'
    assert (target / "app.db").read_bytes() == b"sqlite-placeholder"
    marker = json.loads((target / MIGRATION_MARKER).read_text(encoding="utf-8"))
    assert marker["source"] == str(legacy.resolve())
    assert marker["target"] == str(target.resolve())


def test_migrate_legacy_data_is_idempotent_and_never_overwrites(tmp_path: Path):
    legacy = tmp_path / "legacy"
    target = tmp_path / "desktop"
    source_file = legacy / "saved" / "record.json"
    target_file = target / "saved" / "record.json"
    source_file.parent.mkdir(parents=True)
    target_file.parent.mkdir(parents=True)
    source_file.write_text("legacy", encoding="utf-8")
    target_file.write_text("desktop", encoding="utf-8")

    first = migrate_legacy_data(target, legacy_root=legacy)
    second = migrate_legacy_data(target, legacy_root=legacy)

    assert first["status"] == "completed"
    assert first["skipped_existing"] == 1
    assert second["status"] == "already_completed"
    assert source_file.read_text(encoding="utf-8") == "legacy"
    assert target_file.read_text(encoding="utf-8") == "desktop"
