import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[3] / "data" / "app.db"


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_conn():
    conn = _conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS papers (
                id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_name TEXT NOT NULL,
                local_pdf_path TEXT,
                title TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS parses (
                id TEXT PRIMARY KEY,
                paper_id TEXT NOT NULL,
                parse_status TEXT NOT NULL,
                section_index_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(paper_id) REFERENCES papers(id)
            );

            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                paper_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY(paper_id) REFERENCES papers(id)
            );

            CREATE TABLE IF NOT EXISTS outputs (
                run_id TEXT PRIMARY KEY,
                draft_json TEXT,
                review_json TEXT,
                final_json TEXT,
                changelog_json TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );

            CREATE TABLE IF NOT EXISTS llm_traces (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                phase TEXT NOT NULL,
                provider_slot TEXT NOT NULL,
                provider_name TEXT NOT NULL,
                model TEXT NOT NULL,
                request_system TEXT NOT NULL,
                request_user TEXT NOT NULL,
                response_text TEXT,
                error_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_runs_paper_id ON runs(paper_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_llm_traces_run_id ON llm_traces(run_id, created_at ASC);
            """
        )


def create_paper(source_type: str, source_name: str, local_pdf_path: str | None = None, title: str | None = None) -> dict[str, Any]:
    paper_id = str(uuid.uuid4())
    created_at = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO papers (id, source_type, source_name, local_pdf_path, title, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (paper_id, source_type, source_name, local_pdf_path, title, created_at),
        )
    return get_paper(paper_id)


def get_paper(paper_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        return dict(row) if row else None


def create_run(paper_id: str, mode: str) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    started_at = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO runs (id, paper_id, mode, status, started_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, paper_id, mode, "running", started_at),
        )
        conn.execute("INSERT INTO outputs (run_id) VALUES (?)", (run_id,))
    return get_run(run_id)


def update_run_status(run_id: str, status: str) -> None:
    with get_conn() as conn:
        finished_at = now_iso() if status in {"done", "failed"} else None
        conn.execute(
            "UPDATE runs SET status = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
            (status, finished_at, run_id),
        )


def get_run(run_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def get_latest_run(paper_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE paper_id = ? ORDER BY started_at DESC LIMIT 1",
            (paper_id,),
        ).fetchone()
        return dict(row) if row else None


def save_parse(paper_id: str, parse_status: str, section_index: dict[str, Any]) -> None:
    parse_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO parses (id, paper_id, parse_status, section_index_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (parse_id, paper_id, parse_status, json.dumps(section_index, ensure_ascii=False), now_iso()),
        )


def get_latest_parse(paper_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM parses WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1",
            (paper_id,),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    data["section_index"] = json.loads(data["section_index_json"])
    return data


def save_draft(run_id: str, draft: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE outputs SET draft_json = ? WHERE run_id = ?", (json.dumps(draft, ensure_ascii=False), run_id))


def save_review(run_id: str, review: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE outputs SET review_json = ? WHERE run_id = ?", (json.dumps(review, ensure_ascii=False), run_id))


def save_final(run_id: str, final: dict[str, Any], changelog: list[dict[str, Any]] | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE outputs SET final_json = ?, changelog_json = ? WHERE run_id = ?",
            (
                json.dumps(final, ensure_ascii=False),
                json.dumps(changelog or final.get("change_log", []), ensure_ascii=False),
                run_id,
            ),
        )


def get_outputs(run_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM outputs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        return {}
    data = dict(row)
    for key in ("draft_json", "review_json", "final_json", "changelog_json"):
        if data.get(key):
            data[key] = json.loads(data[key])
    return data


def append_llm_trace(
    *,
    run_id: str,
    phase: str,
    provider_slot: str,
    provider_name: str,
    model: str,
    request_system: str,
    request_user: str,
    response_text: str | None = None,
    error_text: str | None = None,
) -> None:
    trace_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO llm_traces (
                id, run_id, phase, provider_slot, provider_name, model,
                request_system, request_user, response_text, error_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                run_id,
                phase,
                provider_slot,
                provider_name,
                model,
                request_system,
                request_user,
                response_text,
                error_text,
                now_iso(),
            ),
        )


def get_llm_traces(run_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_traces WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]
