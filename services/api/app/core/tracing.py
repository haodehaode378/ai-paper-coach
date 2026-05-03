from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def langsmith_enabled() -> bool:
    return _truthy(os.getenv("LANGSMITH_TRACING"))


def traceable_if_enabled(
    *,
    name: str,
    run_type: str = "chain",
    metadata: Mapping[str, Any] | None = None,
    process_inputs: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    process_outputs: Callable[[Any], dict[str, Any]] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        if not langsmith_enabled():
            return func
        try:
            from langsmith import traceable
        except Exception:
            return func

        return traceable(
            run_type=run_type,
            name=name,
            metadata=dict(metadata or {}),
            project_name=(os.getenv("LANGSMITH_PROJECT") or "").strip() or None,
            process_inputs=process_inputs,
            process_outputs=process_outputs,
        )(func)

    return decorate
