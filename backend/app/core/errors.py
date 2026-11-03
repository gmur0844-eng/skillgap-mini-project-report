"""
Structured API errors and request observability, shared by the full app (app.main) and the
standalone knowledge app (app.knowledge_api).

Every error response has the same shape and never contains a stack trace:

    {"error": "<HTTP reason>", "code": "<MACHINE_CODE>", "message": "<human text>",
     "details": <object|list|null>, "request_id": "<id>"}

Every request is logged as one JSON line (request id, method, path, status, duration, run_id query
parameter when present). Header values, bodies and other query parameters are never logged, so
credentials cannot leak into logs. Unhandled exceptions are logged with their type only.
"""
import json
import logging
import time
import uuid
from http import HTTPStatus

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("skillgap.api")

CODES = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
         409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR",
         429: "TOO_MANY_REQUESTS", 500: "INTERNAL_ERROR", 503: "SERVICE_UNAVAILABLE"}


class ApiError(Exception):
    """Raise from service/route code for a specific, documented error code."""

    def __init__(self, status, code, message, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def error_body(status, code, message, details=None, request_id=None):
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = "Error"
    return {"error": phrase, "code": code or CODES.get(status, "ERROR"), "message": message,
            "details": details, "request_id": request_id}


def _rid(request):
    return getattr(request.state, "request_id", None)


def _json_safe(obj):
    return json.loads(json.dumps(obj, default=str))


async def _http_exc(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        body = error_body(exc.status_code, detail["code"], detail.get("message", ""), detail.get("details"), _rid(request))
    else:
        body = error_body(exc.status_code, None, str(detail) if detail else HTTPStatus(exc.status_code).phrase,
                          None, _rid(request))
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


async def _api_error(request: Request, exc: ApiError):
    return JSONResponse(error_body(exc.status, exc.code, exc.message, _json_safe(exc.details), _rid(request)),
                        status_code=exc.status)


async def _validation(request: Request, exc):
    errors = [{"location": list(e.get("loc", ())), "message": e.get("msg"), "type": e.get("type")}
              for e in exc.errors()]
    return JSONResponse(error_body(422, "VALIDATION_ERROR", "request parameters or body are invalid",
                                   _json_safe(errors), _rid(request)), status_code=422)


async def _unhandled(request: Request, exc: Exception):
    log.error(json.dumps({"event": "unhandled_exception", "request_id": _rid(request), "path": request.url.path,
                          "exception": type(exc).__name__}))
    return JSONResponse(error_body(500, "INTERNAL_ERROR", "an internal error occurred; see server logs by request_id",
                                   None, _rid(request)), status_code=500)


async def request_context(request: Request, call_next):
    """Request id (accepts a well-formed incoming X-Request-ID), structured access log, timing header."""
    incoming = request.headers.get("x-request-id", "")
    rid = incoming if (0 < len(incoming) <= 64 and incoming.replace("-", "").isalnum()) else uuid.uuid4().hex[:16]
    request.state.request_id = rid
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as exc:  # noqa: BLE001 -- converted to the structured 500 below, never re-raised to the client
        response = await _unhandled(request, exc)
    ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Response-Time-ms"] = str(ms)
    log.info(json.dumps({"event": "request", "request_id": rid, "method": request.method, "path": request.url.path,
                         "status": status, "duration_ms": ms, "run_id": request.query_params.get("run_id")}))
    return response


def install(app):
    """Attach the handlers and the request middleware to a Starlette/FastAPI app."""
    app.add_exception_handler(StarletteHTTPException, _http_exc)
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(Exception, _unhandled)
    try:
        from sqlalchemy.exc import OperationalError

        async def _db_down(request, exc):
            log.error(json.dumps({"event": "database_unavailable", "request_id": _rid(request), "path": request.url.path}))
            return JSONResponse(error_body(503, "DATABASE_UNAVAILABLE", "the database is not reachable; file-backed "
                                           "knowledge endpoints remain available", None, _rid(request)), status_code=503)
        app.add_exception_handler(OperationalError, _db_down)
    except ImportError:
        pass
    try:
        from fastapi.exceptions import RequestValidationError
        app.add_exception_handler(RequestValidationError, _validation)
    except ImportError:  # plain Starlette app (tests in an environment without FastAPI)
        pass
    from starlette.middleware.base import BaseHTTPMiddleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=request_context)
    return app
