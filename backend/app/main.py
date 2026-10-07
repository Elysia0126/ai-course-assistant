"""FastAPI application factory."""

import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import chat, courses, documents, flashcards, health, quizzes
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import build_engine, build_session_factory, run_migrations
from app.services.embeddings import build_embedding_provider
from app.services.ingestion import fail_interrupted_documents
from app.services.llm import build_llm_backend

logger = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    embedder = build_embedding_provider(settings)
    llm = build_llm_backend(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        if settings.auto_migrate:
            run_migrations(settings.database_url)
        interrupted = fail_interrupted_documents(session_factory)
        if interrupted:
            logger.warning("Marked %d interrupted document(s) as failed", interrupted)
        if embedder.name == "fastembed" and settings.app_env != "test":
            # Load the ONNX model in the background so the first upload/question isn't slow.
            threading.Thread(target=embedder.embed_query, args=("warm-up",), daemon=True).start()
        logger.info(
            "Ready: db=%s llm=%s/%s embeddings=%s/%s",
            engine.dialect.name,
            llm.name,
            llm.model,
            embedder.name,
            embedder.model,
        )
        yield
        engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Upload course materials and get cited answers, quizzes and flashcards grounded in them.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.embedder = embedder
    app.state.llm = llm

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # Basic hardening: no MIME sniffing of uploads, no framing, no referrer leakage.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path != "/api/health":
            logger.info(
                "%s %s -> %s (%.0f ms) [%s]",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
                request_id,
            )
        return response

    register_exception_handlers(app)

    api = APIRouter(prefix="/api")
    for module in (health, courses, documents, chat, quizzes, flashcards):
        api.include_router(module.router)
    app.include_router(api)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "docs": "/docs", "health": "/api/health"}

    return app


def _create_default_app() -> FastAPI:
    return create_app()


app = _create_default_app()
