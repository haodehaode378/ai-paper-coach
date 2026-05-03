from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.core.rag import run_rag_query
from app.core.schemas import ModelConfig

router = APIRouter(tags=["rag"])


class RagQueryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())

    paper_id: str
    question: str
    top_k: int = 5
    chunk_size: int = 900
    chunk_overlap: int = 120
    use_llm: bool = False
    model_slot: Literal["primary", "secondary"] = "primary"
    report: dict[str, Any] | None = None
    llm_config: ModelConfig | None = Field(default=None, alias="model_config")


@router.post("/rag/query")
def rag_query(req: RagQueryRequest) -> dict[str, Any]:
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    try:
        result = run_rag_query(
            paper_id=req.paper_id,
            question=question,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            top_k=req.top_k,
            model_config=req.llm_config.model_dump() if req.llm_config else None,
            model_slot=req.model_slot,
            use_llm=req.use_llm,
            fallback_report=req.report,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"rag query failed: {exc}") from exc

    if not result["debug"]["chunk_count"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "no searchable chunks found for this paper; upload a text-based PDF "
                "or run analyze first so RAG can fall back to parsed sections"
            ),
        )
    return result
