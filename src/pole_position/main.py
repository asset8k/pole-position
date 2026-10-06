import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from pole_position.auth.router import router as auth_router
from pole_position.chat.router import get_sparse_corpus, router as chat_router
from pole_position.config import settings
from pole_position.database import engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        if settings.validate_corpus_on_startup:
            corpus = await run_in_threadpool(get_sparse_corpus)
            logger.info("Loaded active corpus: %s chunks", corpus.index.chunk_count)
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(title="Pole Position API", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in settings.cors_origins.split(",")
            if origin.strip()
        ],
        allow_credentials=False,  # Authentication uses an explicit bearer token.
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.include_router(chat_router)
    application.include_router(auth_router, prefix="/api")

    @application.get("/api/health")
    async def health_check():
        return {"status": "ok"}

    @application.get("/api/ready")
    def corpus_readiness():
        """Verify local retrieval data without a paid model request."""
        try:
            corpus = get_sparse_corpus()
        except (OSError, ValueError):
            logger.exception("Active corpus is unavailable")
            raise HTTPException(
                status_code=503, detail="Retrieval corpus is unavailable"
            ) from None
        return {"status": "ok", "active_chunks": corpus.index.chunk_count}

    return application


app = create_app()
