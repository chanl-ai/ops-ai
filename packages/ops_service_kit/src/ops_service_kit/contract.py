"""Checks each API response against the app's own OpenAPI document.

Routes return hand-built JSON through `ok()`, which FastAPI does not validate, so a declared model could drift from
what a route sends. Attached as an httpx response hook, this turns every API test into a contract test against the
document a generated SDK would read: a JSON response must be a status the operation documents, and its body must
match that status's schema. The models refuse unknown fields (`additionalProperties: false`), so a field a route adds
and its model lacks fails here. Undocumented operations are skipped; each service's scripts/check_openapi.py keeps
that set from growing.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute
from jsonschema import Draft202012Validator


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
