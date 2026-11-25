"""The error envelope (specs/api.md §2).

Every error is returned as:
    {"error": {"code": "...", "message": "...", "fields": {...}?}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    410: "GONE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        fields: dict[str, list[str]] | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.fields, self.headers, self.extra = fields, headers, extra


def validation_error(fields: dict[str, list[str]], message: str = "Some fields are invalid.") -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", message, fields=fields)


def error_response(
    status: int,
    code: str,
    message: str,
    fields: dict[str, list[str]] | None = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    if extra:
        body.update(extra)
    return JSONResponse({"error": body}, status_code=status, headers=headers)


def field_path(loc: tuple[Any, ...]) -> str:
    """('body', 'parts', 1, 'card_id') -> 'parts[1].card_id'."""
    parts = list(loc[1:]) if loc and loc[0] in ("body", "query", "path", "header", "cookie") else list(loc)
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or "body"


def _clean_message(message: str) -> str:
    return message.removeprefix("Value error, ")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        response = error_response(exc.status, exc.code, exc.message, exc.fields, exc.headers, exc.extra)
        if exc.code == "UNAUTHENTICATED":
            # A session cookie that no longer resolves (expired, revoked, or its database was
            # reset) is cleared, so the UI's route guard stops treating the browser as logged in.
            from app.api.deps import SESSION_COOKIE, clear_auth_cookies  # deps imports this module

            if SESSION_COOKIE in request.cookies:
                clear_auth_cookies(response)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields: dict[str, list[str]] = {}
        for err in exc.errors():
            if err.get("type") == "json_invalid":
                return error_response(400, "BAD_REQUEST", "Malformed JSON body.")
            fields.setdefault(field_path(tuple(err["loc"])), []).append(_clean_message(err["msg"]))
        return error_response(422, "VALIDATION_ERROR", "Some fields are invalid.", fields)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "ERROR")
        return error_response(exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "Something went wrong.")
