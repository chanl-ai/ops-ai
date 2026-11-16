"""The body and reply bases, by failure mode: an unknown field in a body accepted; a date, an enum or a UUID in JSON
refused by a base too strict for FastAPI's parsed body; and the route walk missing a body that is not an `In` or a
reply that is not an `Out` all the way down."""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ops_service_kit import contract, openapi
from ops_service_kit.contract import boundaries
from ops_service_kit.http import (
    Envelope,
    In,
    JsonValue,
    ListResult,
    Out,
    Passthrough,
    install_error_handlers,
    ok,
    operation_id,
    paged,
)


class Colour(enum.StrEnum):
    RED = "red"


class BaseIn(In):
    name: str
    at: datetime.datetime
    colour: Colour
    ref: uuid.UUID


class BaseOut(Out):
    id: str


class Loose(BaseModel):
    name: str


def app() -> FastAPI:
    api = FastAPI(generate_unique_id_function=operation_id)
    install_error_handlers(api)
    router = APIRouter(prefix="/v1/bases", tags=["bases"])

    @router.post("", response_model=Envelope[ListResult[BaseOut]])
    async def create(body: BaseIn) -> JSONResponse:
        return ok(paged([], 0, 1, 20))

    @router.put("/{id}", response_model=Envelope[dict[str, Any]])
    async def replace(id: str, body: Loose) -> dict[str, Any]:
        return {}

    @router.get("/{id}", response_model=Envelope[Loose])
    async def read(id: str) -> dict[str, Any]:
        return {}

    @router.delete("/{id}", status_code=204)
    async def remove(id: str) -> None:
        return None

    api.include_router(router)
    return api


async def test_a_body_refuses_an_unknown_field_and_takes_json_dates_enums_and_ids() -> None:
    body = {"name": "Claims", "at": "2026-11-15T09:00:00Z", "colour": "red", "ref": str(uuid.uuid4())}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url="http://test") as client:
        assert (await client.post("/v1/bases", json=body)).status_code == 200
        refused = await client.post("/v1/bases", json=body | {"nmae": "typo"})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "validation_failed"


def test_the_walk_names_each_body_and_reply_without_a_model() -> None:
    assert boundaries(app()) == [
        ("body", "bases_replace"),
        ("reply", "bases_read"),
        ("reply", "bases_replace"),
    ]


class Dict(Out):
    meta: dict[str, Any]


class Anything(Out):
    value: Any


class Nested(Out):
    inner: list[Loose]


class Fine(Out):
    id: str
    at: datetime.datetime
    colour: Colour
    ref: uuid.UUID
    tags: dict[str, str]
    parts: list[Fine]


class Forwarded(Passthrough):
    payload: str


def planted() -> FastAPI:
    api = FastAPI(generate_unique_id_function=operation_id)
    install_error_handlers(api)

    @api.get("/dict", response_model=Envelope[Dict])
    async def a_dict() -> JSONResponse:
        return ok({})

    @api.get("/any", response_model=Envelope[Anything])
    async def an_any() -> JSONResponse:
        return ok({})

    @api.get("/nested", response_model=Envelope[Nested])
    async def a_nested() -> JSONResponse:
        return ok({})

    @api.get("/fine", response_model=Envelope[Fine])
    async def a_fine() -> JSONResponse:
        return ok({})

    @api.post("/raw", response_model=Envelope[Fine])
    async def raw(request: Request) -> JSONResponse:
        return JSONResponse(await request.json())

    @api.post("/fwd", response_model=Envelope[Fine])
    async def forwarded(body: Forwarded) -> JSONResponse:
        return ok({})

    @api.post("/headers", response_model=Envelope[Fine])
    async def headers(request: Request) -> JSONResponse:
        return ok({"agent": request.headers.get("user-agent")})

    return api


def test_the_walk_follows_fields_raw_bodies_raw_replies_and_unlisted_passthroughs() -> None:
    assert sorted(boundaries(planted())) == [
        ("body", "forwarded"),
        ("body", "raw"),
        ("reply", "a_dict"),
        ("reply", "a_nested"),
        ("reply", "an_any"),
        ("reply", "raw"),
    ]


def test_a_passthrough_on_the_named_list_is_let_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contract, "PASSTHROUGH", frozenset({f"{Forwarded.__module__}.{Forwarded.__qualname__}"}))
    assert ("body", "forwarded") not in boundaries(planted())


class RunOut(Out):
    output: JsonValue


async def test_a_reply_field_holding_any_json_value_is_typed_and_checked() -> None:
    # A function's result is whatever JSON it returned: JsonValue types it without Any, and the reply still has to
    # be JSON (the checker refuses nothing a JSON value may be, and the walk and the gate count the route typed).
    api = FastAPI(generate_unique_id_function=operation_id)
    install_error_handlers(api)

    @api.get("/run", response_model=Envelope[RunOut])
    async def run_read() -> JSONResponse:
        return ok({"output": {"rows": [1, 2.5, None, "x", True], "nested": {"deep": []}}})

    assert boundaries(api) == []
    [op] = [m for p in api.openapi()["paths"].values() for m in p.values()]
    assert openapi.typed(op)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(api),
        base_url="http://kit",
        event_hooks={"response": [contract.response_checker(api)]},
    ) as client:
        assert (await client.get("/run")).json()["data"]["output"]["nested"] == {"deep": []}
