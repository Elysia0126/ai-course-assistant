"""FastAPI application factory."""

import hmac
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.deps import csrf_protect
from app.api.routes import admin, auth, chat, courses, demo, documents, flashcards, health, quizzes
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.security import CSRF_HEADER
from app.db.session import build_engine, build_session_factory, run_migrations
from app.services.embeddings import build_embedding_provider
from app.services.ingestion import fail_interrupted_documents
from app.services.llm import build_llm_backend
from app.services.mailer import build_mailer

logger = logging.getLogger("app")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    embedder = build_embedding_provider(settings)
    llm = build_llm_backend(settings)
    mailer = build_mailer(settings)

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
            "Ready: db=%s llm=%s/%s embeddings=%s/%s mail=%s",
            engine.dialect.name,
            llm.name,
            llm.model,
            embedder.name,
            embedder.model,
            mailer.name,
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
    app.state.mailer = mailer

    api_token = settings.app_api_token.get_secret_value() if settings.app_api_token else ""

    # Only needed for browser apps on other origins; the bundled frontend is same-origin via its proxy.
    # Exact origins only (a wildcard is rejected in Settings) because cookies are involved.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=bool(settings.cors_origins),
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Accept", CSRF_HEADER, "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        started = time.perf_counter()
        path = request.url.path
        if api_token and path.startswith("/api/") and path != "/api/health" and request.method != "OPTIONS":
            supplied = request.headers.get("authorization", "")
            if not hmac.compare_digest(supplied.encode(), f"Bearer {api_token}".encode()):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "code": "service_token_invalid",
                            "message": "This API only accepts requests from the web app's server.",
                            "details": None,
                        }
                    },
                )
            # The caller proved it is our Next.js proxy, so its X-Forwarded-For can be believed.
            request.state.via_trusted_proxy = True
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        # Basic hardening: no MIME sniffing of uploads, no framing, no referrer leakage.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if path.startswith("/api/"):
            # Account and course data is per user: nothing may be stored by browsers or shared caches.
            response.headers.setdefault("Cache-Control", "no-store")
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

    # Every route: CSRF/origin check on state-changing methods. Every route except health and the anonymous
    # auth endpoints additionally declares CurrentUser (or AdminUser) and loads data through ownership checks.
    api = APIRouter(prefix="/api", dependencies=[Depends(csrf_protect)])
    for module in (health, auth, admin, courses, demo, documents, chat, quizzes, flashcards):
        api.include_router(module.router)
    app.include_router(api)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": settings.app_name, "docs": "/docs", "health": "/api/health"}

    return app


def _create_default_app() -> FastAPI:
    return create_app()


app = _create_default_app()
