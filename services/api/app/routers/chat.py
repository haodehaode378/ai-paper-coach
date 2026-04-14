from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.history_store import list_history_records
from app.core.model_router import ModelRouter
from app.core.schemas import ModelConfig
from app.core.storage import list_papers

router = APIRouter(tags=["chat"])


class ChatTurn(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ReportChatRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    report: dict[str, Any]
    messages: list[ChatTurn]
    include_history: bool = True
    include_papers: bool = True
    response_language: Literal["zh", "en", "follow_user"] = "zh"
    model_slot: Literal["primary", "secondary"] = "primary"
    llm_config: ModelConfig | None = Field(default=None, alias="model_config")


def _clip(value: Any, limit: int = 2400) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n..."


def _report_context(report: dict[str, Any]) -> str:
    paper_meta = report.get("paper_meta") or {}
    summary = report.get("three_minute_summary") or {}
    reproduction = report.get("reproduction_guide") or {}
    qa = report.get("reading_qa") or {}

    blocks = [
        f"Title: {_clip(paper_meta.get('title') or '-', 300)}",
        f"Problem and goal: {_clip(summary.get('problem') or '-', 2400)}",
        "Method points:\n- " + "\n- ".join([_clip(item, 300) for item in (summary.get("method_points") or [])[:8]]) if summary.get("method_points") else "Method points: -",
        "Key results:\n- " + "\n- ".join([_clip(item, 300) for item in (summary.get("key_results") or [])[:8]]) if summary.get("key_results") else "Key results: -",
        f"Environment: {_clip(reproduction.get('environment') or '-', 1200)}",
        f"Dataset: {_clip(reproduction.get('dataset') or '-', 1200)}",
        "Commands:\n- " + "\n- ".join([_clip(item, 240) for item in (reproduction.get("commands") or [])[:10]]) if reproduction.get("commands") else "Commands: -",
        "Key hyperparameters:\n- " + "\n- ".join([_clip(item, 240) for item in (reproduction.get("key_hyperparams") or [])[:10]]) if reproduction.get("key_hyperparams") else "Key hyperparameters: -",
    ]

    for key, label in [
        ("q1_problem_and_novelty", "Question 1"),
        ("q2_related_work_and_researchers", "Question 2"),
        ("q3_key_idea", "Question 3"),
        ("q4_experiment_design", "Question 4"),
        ("q5_dataset_and_code", "Question 5"),
        ("q6_support_for_claims", "Question 6"),
        ("q7_contribution_and_next_step", "Question 7"),
    ]:
        blocks.append(f"{label}: {_clip(qa.get(key) or '-', 1500)}")

    return "\n\n".join(blocks)


def _conversation_to_user_text(messages: list[ChatTurn]) -> str:
    trimmed = messages[-12:]
    lines: list[str] = []
    for item in trimmed:
        role = "User" if item.role == "user" else "Assistant"
        lines.append(f"{role}: {item.content.strip()}")
    return "\n\n".join(lines)


def _history_context(limit: int = 8) -> str:
    items = list_history_records()[:limit]
    if not items:
        return "No history records available."
    lines = []
    for item in items:
        lines.append(
            "- "
            f"record_id={item.get('record_id', '-')} | "
            f"paper_id={item.get('paper_id', '-')} | "
            f"title={item.get('title', '-')} | "
            f"stage={item.get('stage', '-')} | "
            f"status={item.get('status', '-')} | "
            f"saved_at={item.get('saved_at', '-')}"
        )
    return "Recent history records:\n" + "\n".join(lines)


def _papers_context(limit: int = 8) -> str:
    items = list_papers(limit=limit)
    if not items:
        return "No paper library entries available."
    lines = []
    for item in items:
        lines.append(
            "- "
            f"paper_id={item.get('id', '-')} | "
            f"title={item.get('title') or '-'} | "
            f"source_type={item.get('source_type', '-')} | "
            f"source_name={item.get('source_name', '-')} | "
            f"created_at={item.get('created_at', '-')}"
        )
    return "Recent papers:\n" + "\n".join(lines)


def _build_system_prompt(
    report: dict[str, Any],
    *,
    include_history: bool,
    include_papers: bool,
    response_language: Literal["zh", "en", "follow_user"],
) -> str:
    language_rule = {
        "zh": "Always answer in Chinese.",
        "en": "Always answer in English.",
        "follow_user": "Follow the user's language in the latest user message.",
    }.get(response_language, "Always answer in Chinese.")

    blocks = [
        "You are an AI paper-reading assistant. "
        "Answer strictly based on the provided context. "
        "Prefer the current report first, then use history records and paper library when they help. "
        "If the context is insufficient, say that clearly. "
        f"{language_rule} "
        "Be direct, readable, and do not invent paper details.",
        "Current report context:\n" + _report_context(report),
    ]
    if include_history:
        blocks.append(_history_context())
    if include_papers:
        blocks.append(_papers_context())
    return "\n\n".join(blocks)


@router.post("/chat/report")
def chat_with_report(req: ReportChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages is empty")

    cfg = req.llm_config.model_dump() if req.llm_config else None
    router_client = ModelRouter(model_config=cfg, trace_phase="chat")
    system = _build_system_prompt(
        req.report,
        include_history=req.include_history,
        include_papers=req.include_papers,
        response_language=req.response_language,
    )
    user_text = _conversation_to_user_text(req.messages)

    try:
        answer = router_client.chat_text(slot=req.model_slot, system=system, user=user_text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"chat failed: {e}") from e

    return {
        "ok": True,
        "message": {
            "role": "assistant",
            "content": answer,
        },
    }


@router.post("/chat/report/stream")
def chat_with_report_stream(req: ReportChatRequest):
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages is empty")

    cfg = req.llm_config.model_dump() if req.llm_config else None
    router_client = ModelRouter(model_config=cfg, trace_phase="chat")
    system = _build_system_prompt(
        req.report,
        include_history=req.include_history,
        include_papers=req.include_papers,
        response_language=req.response_language,
    )
    user_text = _conversation_to_user_text(req.messages)

    def event_stream():
        try:
            for chunk in router_client.chat_text_stream(slot=req.model_slot, system=system, user=user_text):
                if not chunk:
                    continue
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'chat failed: {e}'}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )