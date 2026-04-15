from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import storage
from app.routers import ingest as ingest_router
from app.main import create_app


@pytest.fixture()
def client_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    @contextmanager
    def _build_client(env: dict[str, str] | None = None):
        db_path = tmp_path / "app.db"
        uploads_root = tmp_path / "uploads"
        uploads_root.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(storage, "DB_PATH", db_path)
        monkeypatch.setattr(ingest_router, "UPLOAD_ROOT", uploads_root)

        for name in ("APC_ALLOWED_ORIGINS", "APC_REQUIRE_API_KEY", "APC_API_KEY", "APC_MAX_UPLOAD_MB"):
            monkeypatch.delenv(name, raising=False)
        for name, value in (env or {}).items():
            monkeypatch.setenv(name, value)

        app = create_app()
        with TestClient(app) as test_client:
            yield test_client

    return _build_client


@pytest.fixture()
def client(client_factory):
    with client_factory() as test_client:
        yield test_client
