"""Checks each API response against the app's own OpenAPI document.

Routes return hand-built JSON through `ok()`, which FastAPI does not validate, so a declared model could drift from
what a route sends. Attached as an httpx response hook, this turns every API test into a contract test against the
document a generated SDK would read: a JSON response must be a status the operation documents, and its body must
match that status's schema. The models refuse unknown fields (`additionalProperties: false`), so a field a route adds
and its model lacks fails here. Undocumented operations are skipped; each service's scripts/check_openapi.py keeps
that set from growing.

`boundaries(app)` walks the routes themselves, where the document cannot tell: each request body must be an `In`
and each reply an `Out` all the way down (`MD1`, `MD4`). scripts/check_typed_boundaries.py runs it on every service
against that service's shrink-only list.
"""

from __future__ import annotations

import ast
import datetime
import decimal
import enum
import inspect
import re
import textwrap
import types
import uuid
from collections.abc import Iterator
from typing import Any, Literal, Union, get_args, get_origin

import httpx
from fastapi import FastAPI, params
from fastapi.datastructures import DefaultPlaceholder
from fastapi.dependencies.models import Dependant
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, iter_route_contexts
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from .http import In, JsonValue, Out, Passthrough

# The body models that forward their JSON whole to an outside system, named `module.Class`. A `Passthrough` subclass
# anywhere else is a body finding; a name is added here only in a reviewed change.
PASSTHROUGH: frozenset[str] = frozenset()


class Contract:
    def __init__(self, app: FastAPI) -> None:
        doc = app.openapi()
        self.components: dict[str, Any] = doc.get("components", {})
        self.operations: list[tuple[re.Pattern[str], str, dict[str, Any]]] = []
        for path, ops in doc["paths"].items():
            pattern = re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$")
            for method, op in ops.items():
                self.operations.append((pattern, method.upper(), op))

    def operation(self, method: str, path: str) -> dict[str, Any] | None:
        return next((op for p, m, op in self.operations if m == method and p.match(path)), None)

    def check(self, method: str, path: str, status: int, body: Any) -> None:
        op = self.operation(method, path)
        if op is None or (status < 400 and not typed(op)):
            # Untyped operations are on check_openapi's shrinking allowlist; their errors are still checked.
            return
        documented = op["responses"].get(str(status))
        assert documented is not None, f"{op['operationId']} answered {status}, which it does not document"
        schema = documented.get("content", {}).get("application/json", {}).get("schema")
        assert schema is not None, f"{op['operationId']} documents {status} with no JSON schema"
        validator = Draft202012Validator({**schema, "components": self.components})
        errors = sorted(validator.iter_errors(body), key=lambda e: list(e.path))  # pyright: ignore[reportUnknownMemberType]
        if errors:
            where = "/".join(str(p) for p in errors[0].path)
            raise AssertionError(
                f"{op['operationId']} {status} does not match its schema at {where}: {errors[0].message}"
            )


def typed(op: dict[str, Any]) -> bool:
    """Whether a success response declares a schema: FastAPI's default for a route with no model is `{}`."""
    for status, r in op["responses"].items():
        if status.startswith("2") and r.get("content", {}).get("application/json", {}).get("schema") not in (None, {}):
            return True
    return False


# One contract per distinct app for the whole test session. Every API test builds a fresh app, and building the
# document (app.openapi(), then a pattern per route) took 1.1 s on agents-service's app, so a suite spent minutes on it.
_CONTRACTS: dict[tuple[Any, ...], Contract] = {}


def app_shape(app: FastAPI) -> tuple[Any, ...]:
    """What an app's response contract is built from: each API route's path, methods, handler, response model, status
    code and extra documented responses. Two apps share a contract only when all of it matches; a model built per app
    (a different class each time) makes the shapes differ, so that app gets its own contract."""
    return tuple(
        (
            r.path,
            tuple(sorted(r.methods or ())),
            r.endpoint,
            r.response_model,
            r.status_code,
            repr(sorted((str(k), repr(v)) for k, v in (r.responses or {}).items())),
            r.include_in_schema,
        )
        for r in app.routes
        if isinstance(r, APIRoute)
    )


def contract_for(app: FastAPI) -> Contract:
    """The app's contract, built once for every app of the same shape."""
    key = app_shape(app)
    if key not in _CONTRACTS:
        _CONTRACTS[key] = Contract(app)
    return _CONTRACTS[key]


def response_checker(app: FastAPI) -> Any:
    contract: list[Contract] = []

    async def check(response: httpx.Response) -> None:
        if "application/json" not in response.headers.get("content-type", ""):
            return
        await response.aread()
        if not contract:
            contract.append(contract_for(app))
        request = response.request
        contract[0].check(request.method, request.url.path, response.status_code, response.json())

    return check


# A reply part that is typed without being a model.
_SCALARS: tuple[type, ...] = (
    str,
    int,
    float,
    bool,
    type(None),
    datetime.datetime,
    datetime.date,
    datetime.time,
    decimal.Decimal,
    uuid.UUID,
    enum.Enum,
)


def _out(t: Any, seen: frozenset[type] = frozenset()) -> bool:
    """Whether a reply type is an `Out` all the way down: an Out whose generic arguments (Envelope[T], ListResult[T])
    and whose field types are Outs or scalars, or a list, tuple, set, union, Literal or `dict[str, X]` of those, or a
    `JsonValue`. `Any`, `object` and a bare or `Any`-valued dict are not typed."""
    if t is JsonValue or get_origin(t) is Literal:
        return True
    if isinstance(t, type) and issubclass(t, _SCALARS):
        return True
    if isinstance(t, type) and issubclass(t, BaseModel):
        if not issubclass(t, Out):
            return False
        if t in seen:
            return True
        meta: dict[str, Any] = getattr(t, "__pydantic_generic_metadata__", {}) or {}
        if not all(_out(a, seen) for a in meta.get("args", ())):
            return False
        return all(_out(f.annotation, seen | {t}) for f in t.model_fields.values())
    origin = get_origin(t)
    if origin in (list, tuple, set, frozenset, Union, types.UnionType):
        return all(_out(a, seen) for a in get_args(t) if a is not Ellipsis)
    if origin is dict:
        args = get_args(t)
        return len(args) == 2 and _out(args[0], seen) and _out(args[1], seen)
    return False


def _bodies(dependant: Dependant) -> Iterator[Any]:
    """Every JSON body parameter of a route and of the dependencies it takes; a form or a file is not a JSON body."""
    for field in dependant.body_params:
        if not isinstance(field.field_info, params.Form):  # File is a Form
            yield field.field_info.annotation
    for sub in dependant.dependencies:
        yield from _bodies(sub)


def _passthrough(body: Any) -> bool:
    """Whether a body is a `Passthrough` that is not on the named list."""
    return (
        isinstance(body, type)
        and issubclass(body, Passthrough)
        and f"{body.__module__}.{body.__qualname__}" not in PASSTHROUGH
    )


def _reads(fn: Any) -> tuple[bool, bool]:
    """(reads the request body, builds a `JSONResponse` itself) from a function's source: a call to `.json()`,
    `.body()`, `.form()` or `.stream()`, and a direct `JSONResponse(...)` call, which skips the envelope `ok()`."""
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    except (OSError, TypeError, SyntaxError):
        return False, False
    reads = raw = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("json", "body", "form", "stream"):
                reads = True
            if (isinstance(node.func, ast.Name) and node.func.id == "JSONResponse") or (
                isinstance(node.func, ast.Attribute) and node.func.attr == "JSONResponse"
            ):
                raw = True
    return reads, raw


def _calls(dependant: Dependant) -> Iterator[Any]:
    """The route's endpoint and the dependencies it takes."""
    if dependant.call is not None:
        yield dependant.call
    for sub in dependant.dependencies:
        yield from _calls(sub)


def _json_reply(route: APIRoute) -> bool:
    """Whether the route answers JSON in the body: not a 204, a redirect, a stream or a page."""
    cls: Any = route.response_class
    cls = cls.value if isinstance(cls, DefaultPlaceholder) else cls
    return route.status_code not in (204, 301, 302, 303, 307, 308) and issubclass(cls, JSONResponse)


def boundaries(app: FastAPI) -> list[tuple[str, str]]:
    """Each (kind, operation id) of `app` that breaks the model rule: `body` for a JSON request body that is not an
    `In`, `reply` for a JSON reply whose model is missing or is not an `Out` all the way down. A route outside the
    document is skipped; a route with two bad bodies is one finding. Operation ids are the document's."""
    paths: dict[str, dict[str, Any]] = app.openapi()["paths"]
    found: set[tuple[str, str]] = set()
    for ctx in iter_route_contexts(app.routes):
        route = ctx.original_route
        if not isinstance(route, APIRoute) or not ctx.include_in_schema:
            continue
        ops = paths.get(ctx.path_format or "", {})
        for op in {str(ops[m.lower()]["operationId"]) for m in ctx.methods or () if m.lower() in ops}:
            bodies = list(_bodies(ctx.dependant))
            for body in bodies:
                if not (isinstance(body, type) and issubclass(body, In)) or _passthrough(body):
                    found.add(("body", op))
            reads, raw = _reads(route.endpoint)
            for call in _calls(ctx.dependant):
                if call is not route.endpoint:
                    reads = reads or _reads(call)[0]
            if reads and not bodies:
                found.add(("body", op))  # the body is read off `Request`, so no model checks it
            if _json_reply(route) and (raw or route.response_model is None or not _out(route.response_model)):
                found.add(("reply", op))
    return sorted(found)
