from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.routers import analyze, chat, export, ingest, records
from app.core.storage import init_db, mark_stale_pipeline_jobs


def _success(data: Any) -> dict[str, Any]:
    return {
        "success": True,
        "data": data,
        "error": None,
    }


def _failure(message: str, *, code: int, details: Any | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
    }


def _is_enveloped(obj: Any) -> bool:
    return isinstance(obj, dict) and {"success", "data", "error"}.issubset(set(obj.keys()))


def create_app() -> FastAPI:
    app = FastAPI(title="AI Paper Coach API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()
        mark_stale_pipeline_jobs()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": app.title,
            "version": app.version,
        }

    @app.middleware("http")
    async def envelope_json_response(request: Request, call_next):
        response = await call_next(request)

        # Keep docs/openapi untouched.
        if request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            return response

        content_type = (response.headers.get("content-type") or "").lower()
        if "application/json" not in content_type:
            return response

        # Stream responses must not be consumed/wrapped here.
        if "text/event-stream" in content_type:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        if not body:
            payload: Any = None
        else:
            try:
                payload = json.loads(body)
            except Exception:
                # Not valid JSON body; keep original payload text as-is.
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type="application/json",
                )

        if _is_enveloped(payload):
            wrapped = payload
        elif response.status_code >= 400:
            message = "request failed"
            details = payload
            if isinstance(payload, dict):
                message = str(payload.get("detail") or payload.get("message") or message)
            wrapped = _failure(message, code=response.status_code, details=details)
        else:
            wrapped = _success(payload)

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return JSONResponse(status_code=response.status_code, content=wrapped, headers=headers)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_failure(str(exc.detail), code=exc.status_code),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_failure("request validation failed", code=422, details=exc.errors()),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content=_failure(f"internal server error: {exc}", code=500),
        )

    app.include_router(ingest.router)
    app.include_router(analyze.router)
    app.include_router(export.router)
    app.include_router(records.router)
    app.include_router(chat.router)
    return app


app = create_app()
