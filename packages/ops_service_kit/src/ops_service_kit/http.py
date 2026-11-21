"""The response envelope every service speaks (apps/console/src/lib/api/http.ts): `{success, data}` or
`{success: false, error}`, the models that document it in OpenAPI, and the error handlers that produce it.

Routes build their JSON by hand and return it through `ok()`, so FastAPI documents these models without validating
against them; `ops_service_kit.contract` closes that gap in each service's tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Generic, Literal, NotRequired, TypedDict, cast

from fastapi import FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import BaseModel, ConfigDict
from pydantic import JsonValue as _Json
from pydantic.alias_generators import to_camel
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from typing_extensions import TypeVar

from ops_contracts.errors import Code, ErrorKind

from .errors import ApiError, TooManyRequests, error_row
from .ids import new_id
from .listing import page_sizes
from .logging import get_logger
from .request_timing import RequestTimingMiddleware, current_request_id
from .settings import Settings

log = get_logger("ops_service_kit.http")


class In(BaseModel):
    """The base of every request body: an unknown field answers 400 (`MD1`). Not `strict`: FastAPI validates the
    parsed JSON in Python mode, where strict refuses an ISO date string, an enum's value and a UUID string."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# Any JSON value (object, list, string, number, boolean or null, nested to any depth): the type of a reply field that
# holds whatever a function or a document returned (a run's output). It is not `Any`: a value that is not JSON is
# refused, its schema is the named `JsonValue`, and `contract.boundaries` counts it typed.
type JsonValue = _Json
# A JSON object and a JSON list. Plain aliases, not `type` statements: a model field typed with one keeps the inline
# object or array schema it had, so no committed OpenAPI document gains a named component.
Json = dict[str, JsonValue]
JsonList = list[JsonValue]


class Out(BaseModel):
    """The base of every reply and every row a store returns (`MD4`). It refuses a field it does not name, so its
    schema says `additionalProperties: false` and a row with a column the model lacks fails in `ops_store.rows`."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", frozen=True, from_attributes=True
    )


class ExternalIn(In):
    """A body in an outside system's wire format (OpenAI's `max_tokens`): field names as declared, no camelCase alias,
    and an unknown field still answers 400."""

    model_config = ConfigDict(alias_generator=None)


class ExternalOut(Out):
    """A reply in an outside system's wire format (OpenAI's `finish_reason`, `prompt_tokens`): field names as declared,
    no camelCase alias. Its schema matches a plain `extra="forbid"` model's, so converting one leaves the document as
    it is."""

    model_config = ConfigDict(alias_generator=None)


class Passthrough(In):
    """A body forwarded whole to an outside system: the one reviewed exception to extra="forbid"."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")


class Envelope[T](Out):
    success: Literal[True]
    data: T


class ErrorBody(Out):
    code: str
    message: str
    status: int
    request_id: str
    # The error model's kind and whether trying the same call again can help (ops_contracts.errors.CODES), so no
    # caller keeps its own table of what a status means.
    kind: ErrorKind
    retryable: bool
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


def tag_name(tag: str) -> str:
    """A tag as it starts an operation name: `Knowledge-bases` -> `knowledge_bases`."""
    return tag.lower().replace("-", "_").replace(" ", "_")


def operation_id(route: APIRoute) -> str:
    """`<tag>_<handler>`, e.g. `files_delete_file`: every service's `generate_unique_id_function`. The name stays put
    when a path changes, and it is the method name a generated SDK gives the operation."""
    return f"{tag_name(str(route.tags[0]))}_{route.name}" if route.tags else route.name


# Who may call an operation, on every operation of every service's OpenAPI document: `sdk` routes are generated into
# the SDKs and CLI, `tool` routes are offered to agents as platform tools, `both` is each, and `internal` routes take a
# service token and are in neither. ops_identity.fastapi sets it; a route may set its own through `openapi_extra`.
PUBLIC_MARK = "x-ops-public"
PUBLIC_MARKS = ("sdk", "tool", "both", "internal")


def _depends_on(dependant: Dependant, calls: tuple[Callable[..., Any], ...]) -> bool:
    return any(d.call in calls or _depends_on(d, calls) for d in dependant.dependencies)


def mark_public(app: FastAPI, *, service_only: tuple[Callable[..., Any], ...] = (), default: str = "sdk") -> None:
    """Puts `x-ops-public` on every operation of `app`'s document when it is built: `internal` for a route that
    depends on one of `service_only` (the dependency that accepts a service token and nothing else), `default` for the
    rest, and a value the route set itself is kept."""
    build = app.openapi

    def openapi() -> dict[str, Any]:
        doc = build()  # FastAPI caches the document and rebuilds it when routes change; marking it again is a no-op
        # Included routers are nested in app.routes; iter_route_contexts gives each route with its full path and the
        # router-level dependencies, as FastAPI's own document generation reads them.
        for route in iter_route_contexts(app.routes):
            if not isinstance(route.original_route, APIRoute) or not route.include_in_schema:
                continue
            mark = "internal" if _depends_on(route.dependant, service_only) else default
            for method in route.methods or ():
                op = doc["paths"].get(route.path_format, {}).get(method.lower())
                if op is not None:
                    op.setdefault(PUBLIC_MARK, mark)
        return doc

    app.openapi = openapi


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


class LabelledListResult[T](ListResult[T]):
    """A list whose facet values are ids, with the label of each (`ops_store.listing.list_page(labels=...)`). Its
    own model, so the document of every list without labels stays as it is."""

    labels: dict[str, dict[str, str]]


class Option(Out):
    """One choice in a picker: what it stores, what it shows, a short hint, and why it cannot be chosen when it
    cannot (the agent lacks a tool the widget needs, say)."""

    id: str
    label: str
    hint: str | None = None
    disabled: str | None = None


class OptionsPage(Out):
    """A page of a picker's choices, searched and limited in the store query. `next_cursor` asks for the next page;
    None at the end. Every `/options` route answers this, and `ids=` resolves stored values to their labels."""

    data: list[Option]
    next_cursor: str | None = None


def options_window(cursor: str | None, limit: int) -> tuple[int, int]:
    """The offset and limit an `/options` query runs with: the cursor is the offset of the next page, opaque to the
    console. One extra row is read so the route knows whether a next page exists."""
    offset = int(cursor) if cursor and cursor.isdigit() else 0
    return offset, limit + 1


# A page's row: a caller whose rows have a named shape (a TypedDict, a model's dump) gets the page back typed with
# them, with no copy; a bare `ListPage` or `OptionsJSON` holds the dict of each row's columns.
R = TypeVar("R", default=dict[str, Any])


class OptionsJSON(TypedDict, Generic[R]):
    """The `OptionsPage` JSON, as `options_page()` builds it."""

    data: list[R]
    nextCursor: str | None


def options_page(rows: list[R], offset: int, limit: int) -> OptionsJSON[R]:
    """The OptionsPage JSON for rows read with `options_window` (up to limit + 1 of them)."""
    more = len(rows) > limit
    return {"data": rows[:limit], "nextCursor": str(offset + limit) if more else None}


def page_window(total: int, page: int, page_size: int) -> tuple[int, int]:
    """The page to answer and its row offset, for a store query's LIMIT and OFFSET: a page past the end answers the
    last one. `total` is the store's COUNT of the rows the caller may see."""
    pages = max(1, -(-total // page_size))
    page = max(1, min(page, pages))
    return page, (page - 1) * page_size


class PageJSON(TypedDict):
    """The `Pagination` JSON, as `pagination()` builds it."""

    page: int
    pageSize: int
    total: int
    totalPages: int
    hasNext: bool
    hasPrev: bool


def pagination(total: int, page: int, page_size: int) -> PageJSON:
    """The `Pagination` JSON of one page: the one place its keys are built."""
    pages = max(1, -(-total // page_size))
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": pages,
        "hasNext": page < pages,
        "hasPrev": page > 1,
    }


class ListPage(TypedDict, Generic[R]):
    """The `ListResult` JSON, or `LabelledListResult` when the caller asked for labels."""

    data: list[R]
    pagination: PageJSON
    facets: dict[str, dict[str, int]]
    labels: NotRequired[dict[str, dict[str, str]]]


def paged(
    rows: list[R],
    total: int,
    page: int,
    page_size: int,
    *,
    facets: dict[str, dict[str, int]] | None = None,
    labels: dict[str, dict[str, str]] | None = None,
) -> ListPage[R]:
    """The ListResult JSON for one page the store already limited to `page_size` rows; with `labels`, the
    LabelledListResult JSON."""
    out: ListPage[R] = {"data": rows, "pagination": pagination(total, page, page_size), "facets": facets or {}}
    if labels is not None:
        out["labels"] = labels
    return out


def ok(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse({"success": True, "data": data}, status_code=status)


class ErrorJSON(TypedDict):
    """`ErrorBody` as `error_body` builds it. `details` is added by whoever has some, any value `ErrorBody.details`
    documents (an error's details, a validation error list, a refused call's reasons)."""

    code: str
    message: str
    status: int
    requestId: str
    kind: ErrorKind
    retryable: bool
    details: NotRequired[object]


class ErrorBodyJSON(TypedDict):
    """`ErrorEnvelope` as `error_body` builds it."""

    success: Literal[False]
    error: ErrorJSON


def error_body(status: int, code: str, message: str, *, row: Code | None = None) -> ErrorBodyJSON:
    """The error envelope; `kind` and `retryable` come from `row` (an ApiError's `row`), else the code's own row or
    its status's (ops_service_kit.errors.error_row)."""
    # The request's own id, so a reported error leads to its log lines; minted when built outside a request.
    request_id = current_request_id() or new_id("req")
    said = row or error_row(status, code)
    error: ErrorJSON = {
        "code": code,
        "message": message,
        "status": status,
        "requestId": request_id,
        "kind": said.kind,
        "retryable": said.retryable,
    }
    return {"success": False, "error": error}


class _UnhandledAsEnvelope:
    """Turns an exception no handler took into the 500 envelope, innermost of the user middleware. Starlette runs the
    `Exception` handler in ServerErrorMiddleware, outside every user middleware, so its response would skip CORS and the
    browser would report a CORS failure instead of the 500. A response already started is left to fail as it is."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracked(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked)
        except Exception as e:
            if started:
                raise
            log.exception("unhandled_error", error=type(e).__name__)
            response = JSONResponse(error_body(500, "internal", "Something went wrong on the server."), status_code=500)
            await response(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    # Appended, not added: add_middleware puts a middleware outermost, and this one must sit inside CORS whichever order
    # a service calls them in.
    if not any(m.cls is _UnhandledAsEnvelope for m in app.user_middleware):
        app.user_middleware.append(Middleware(_UnhandledAsEnvelope))
    # Just outside the envelope, so the request's id is still set when the 500 envelope is built.
    if not any(m.cls is RequestTimingMiddleware for m in app.user_middleware):
        at = next(i for i, m in enumerate(app.user_middleware) if m.cls is _UnhandledAsEnvelope)
        timing = Middleware(RequestTimingMiddleware, enabled=Settings().request_timing)
        app.user_middleware.insert(at, timing)
    # Every service builds its app here, so the list sizes are read at start rather than by the first list request.
    page_sizes()

    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        body = error_body(e.status, e.code, e.message, row=e.row)
        if e.details:
            body["error"]["details"] = e.details
        wait = e.retry_after_s if isinstance(e, TooManyRequests) else None
        return JSONResponse(body, status_code=e.status, headers={"Retry-After": str(wait)} if wait else None)

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

    # Still needed for an exception raised in a user middleware outside _UnhandledAsEnvelope.
    @app.exception_handler(Exception)
    async def unexpected(_: Request, e: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        # An exception handler is not an except block, so the exception is passed, not read from sys.exc_info().
        log.error("unhandled_error", error=type(e).__name__, exc_info=e)
        return JSONResponse(error_body(500, "internal", "Something went wrong on the server."), status_code=500)
