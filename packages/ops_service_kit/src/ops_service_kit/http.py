"""The response envelope every service speaks (apps/console/src/lib/api/http.ts): `{success, data}` or
`{success: false, error}`, the models that document it in OpenAPI, and the error handlers that produce it.

Routes build their JSON by hand and return it through `ok()`, so FastAPI documents these models without validating
against them; `ops_service_kit.contract` closes that gap in each service's tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from starlette.exceptions import HTTPException

from .errors import ApiError
from .ids import new_id
from .logging import get_logger

log = get_logger("ops_service_kit.http")


class Out(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Envelope[T](Out):
    success: Literal[True]
    data: T


class ErrorBody(Out):
    code: str
    message: str
    status: int
    request_id: str
    details: Any = None


class ErrorEnvelope(Out):
    success: Literal[False]
    error: ErrorBody


ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "Invalid request",
    401: "Not signed in",
    403: "Not allowed",
    404: "Not found",
    409: "Conflicts with the current state",
    422: "Refused by a rule",
    429: "Over a budget or rate limit",
    500: "Server error",
    503: "Service unavailable",
}


def error_responses(overrides: Mapping[int, str] | None = None) -> dict[int | str, dict[str, Any]]:
    """The `responses=` a route declares for its errors; a service rewords any status through `overrides`."""
    descriptions = {**ERROR_DESCRIPTIONS, **(overrides or {})}
    return {status: {"model": ErrorEnvelope, "description": text} for status, text in descriptions.items()}


class Pagination(Out):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ListResult[T](Out):
    data: list[T]
    pagination: Pagination
    facets: dict[str, dict[str, int]]


def ok(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse({"success": True, "data": data}, status_code=status)


def error_body(status: int, code: str, message: str) -> dict[str, Any]:
    return {"success": False, "error": {"code": code, "message": message, "status": status, "requestId": new_id("req")}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        body = error_body(e.status, e.code, e.message)
        if e.details:
            body["error"]["details"] = e.details
        return JSONResponse(body, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, e: RequestValidationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        errors = cast(list[dict[str, Any]], e.errors())
        first: dict[str, Any] = errors[0] if errors else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = (
            f"{where}: {first.get('msg', 'invalid request')}" if where else str(first.get("msg", "invalid request"))
        )
        body = error_body(400, "validation_failed", message)
        body["error"]["details"] = [{"loc": list(x.get("loc", [])), "msg": x.get("msg")} for x in errors]
        return JSONResponse(body, status_code=400)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, e: HTTPException) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        code = "not_found" if e.status_code == 404 else "http_error"
        return JSONResponse(error_body(e.status_code, code, str(e.detail)), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, e: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        log.exception("unhandled_error", error=type(e).__name__)
        return JSONResponse(error_body(500, "internal", "Something went wrong on the server."), status_code=500)
