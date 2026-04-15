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
                meta_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            );


            CREATE TABLE IF NOT EXISTS pipeline_jobs (
                job_id TEXT PRIMARY KEY,
                paper_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                strict INTEGER NOT NULL,
                status TEXT NOT NULL,
                current_stage TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_text TEXT,
                result_json TEXT,
                events_json TEXT NOT NULL,
                next_event_id INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_created_at ON pipeline_jobs(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_runs_paper_id ON runs(paper_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_llm_traces_run_id ON llm_traces(run_id, created_at ASC);
            """
        )
        llm_trace_cols = {str(row["name"]) for row in conn.execute("PRAGMA table_info(llm_traces)").fetchall()}
        if "meta_json" not in llm_trace_cols:
            conn.execute("ALTER TABLE llm_traces ADD COLUMN meta_json TEXT")


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


def list_papers(limit: int = 20) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM papers ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


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
    meta: dict[str, Any] | None = None,
) -> None:
    trace_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO llm_traces (
                id, run_id, phase, provider_slot, provider_name, model,
                request_system, request_user, response_text, error_text, meta_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else None,
                now_iso(),
            ),
        )


def get_llm_traces(run_id: str) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_traces WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    traces: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw_meta = item.get("meta_json")
        if isinstance(raw_meta, str) and raw_meta.strip():
            try:
                item["meta"] = json.loads(raw_meta)
            except Exception:
                item["meta"] = None
        else:
            item["meta"] = None
        traces.append(item)
    return traces



def save_pipeline_job(job: dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO pipeline_jobs (
                job_id, paper_id, mode, strict, status, current_stage,
                created_at, updated_at, error_text, result_json, events_json, next_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                paper_id = excluded.paper_id,
                mode = excluded.mode,
                strict = excluded.strict,
                status = excluded.status,
                current_stage = excluded.current_stage,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                error_text = excluded.error_text,
                result_json = excluded.result_json,
                events_json = excluded.events_json,
                next_event_id = excluded.next_event_id
            """,
            (
                job.get("job_id"),
                job.get("paper_id"),
                job.get("mode", "deep"),
                1 if job.get("strict") else 0,
                job.get("status", "running"),
                job.get("current_stage", "pending"),
                job.get("created_at") or now_iso(),
                job.get("updated_at") or now_iso(),
                job.get("error"),
                json.dumps(job.get("result"), ensure_ascii=False),
                json.dumps(job.get("events") or [], ensure_ascii=False),
                int(job.get("next_event_id") or 1),
            ),
        )


def _decode_pipeline_job_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["strict"] = bool(data.get("strict"))
    try:
        data["result"] = json.loads(data.get("result_json") or "null")
    except Exception:
        data["result"] = None
    try:
        data["events"] = json.loads(data.get("events_json") or "[]")
    except Exception:
        data["events"] = []
    data["error"] = data.get("error_text")
    data["next_event_id"] = int(data.get("next_event_id") or (len(data["events"]) + 1))
    return {
        "job_id": data.get("job_id"),
        "paper_id": data.get("paper_id"),
        "mode": data.get("mode", "deep"),
        "strict": data.get("strict", False),
        "status": data.get("status", "running"),
        "current_stage": data.get("current_stage", "pending"),
        "created_at": data.get("created_at") or now_iso(),
        "updated_at": data.get("updated_at") or now_iso(),
        "error": data.get("error"),
        "result": data.get("result"),
        "events": data.get("events") or [],
        "next_event_id": data.get("next_event_id", 1),
    }


def get_pipeline_job(job_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM pipeline_jobs WHERE job_id = ?", (job_id,)).fetchone()
    if not row:
        return None
    return _decode_pipeline_job_row(row)


def mark_stale_pipeline_jobs(*, reason: str = "service restarted before task finished") -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_jobs WHERE status = 'running'"
        ).fetchall()
        updated = 0
        for row in rows:
            job = _decode_pipeline_job_row(row)
            job["status"] = "failed"
            job["current_stage"] = "interrupted"
            if not job.get("error"):
                job["error"] = reason
            events = list(job.get("events") or [])
            event_id = int(job.get("next_event_id") or (len(events) + 1))
            events.append(
                {
                    "id": event_id,
                    "type": "failed",
                    "stage": "interrupted",
                    "message": reason,
                    "data": None,
                    "ts": now_iso(),
                }
            )
            job["events"] = events[-500:]
            job["next_event_id"] = event_id + 1
            job["updated_at"] = now_iso()
            conn.execute(
                """
                UPDATE pipeline_jobs
                SET status = ?, current_stage = ?, updated_at = ?, error_text = ?, events_json = ?, next_event_id = ?
                WHERE job_id = ?
                """,
                (
                    job["status"],
                    job["current_stage"],
                    job["updated_at"],
                    job.get("error"),
                    json.dumps(job["events"], ensure_ascii=False),
                    int(job["next_event_id"]),
                    job["job_id"],
                ),
            )
            updated += 1
    return updated
