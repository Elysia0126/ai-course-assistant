"""Domain errors and the FastAPI handlers that render them as a consistent JSON shape.

Every error response looks like::

    {"error": {"code": "not_found", "message": "Course not found", "details": null}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self, message: str, *, details: Any = None, code: str | None = None, headers: dict[str, str] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.details = details
        self.headers = headers
        if code:
            self.code = code


class InputError(AppError):
    """A request field that failed a server-side rule (same shape as schema validation errors)."""

    status_code = 422
    code = "validation_error"

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}", details=[{"field": field, "message": message}])


class AuthenticationError(AppError):
    status_code = 401
    code = "authentication_required"

    def __init__(self, message: str = "Please sign in to continue.", *, code: str | None = None, expired: bool = False):
        super().__init__(message, code=code or ("session_expired" if expired else None))
        # A stale session cookie is cleared in the 401 response so the browser stops sending it.
        self.clear_session_cookie = expired


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"


class CSRFError(AppError):
    status_code = 403
    code = "csrf_failed"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, retry_after: int):
        retry_after = max(1, retry_after)
        super().__init__(
            f"Too many attempts. Try again in {retry_after} seconds.",
            details={"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class UnsupportedFileError(AppError):
    status_code = 415
    code = "unsupported_file_type"


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"


class DocumentParsingError(AppError):
    status_code = 422
    code = "document_parsing_failed"


class NoMaterialsError(AppError):
    status_code = 409
    code = "no_materials"


class LLMError(AppError):
    status_code = 502
    code = "llm_error"


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"


def _error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        response = JSONResponse(
            status_code=exc.status_code, content=_error_body(exc.code, exc.message, exc.details), headers=exc.headers
        )
        if getattr(exc, "clear_session_cookie", False):
            from app.core.security import clear_session_cookie

            clear_session_cookie(response, request.app.state.settings)
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in err.get("loc", []) if p != "body"), "message": err.get("msg")}
            for err in exc.errors()
        ]
        first = details[0] if details else {"field": "", "message": "Invalid request"}
        message = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
        return JSONResponse(status_code=422, content=_error_body("validation_error", message, details))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, content=_error_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(status_code=500, content=_error_body("internal_error", "An unexpected error occurred."))
