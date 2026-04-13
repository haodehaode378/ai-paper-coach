from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import analyze, chat, export, ingest, records
from app.core.storage import init_db


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

    app.include_router(ingest.router)
    app.include_router(analyze.router)
    app.include_router(export.router)
    app.include_router(records.router)
    app.include_router(chat.router)
    return app


app = create_app()