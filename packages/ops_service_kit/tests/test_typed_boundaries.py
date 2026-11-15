"""The body and reply bases, by failure mode: an unknown field in a body accepted; a date, an enum or a UUID in JSON
refused by a base too strict for FastAPI's parsed body; and the route walk missing a body that is not an `In` or a
reply that is not an `Out` all the way down."""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ops_service_kit.contract import boundaries
from ops_service_kit.http import Envelope, In, ListResult, Out, install_error_handlers, ok, operation_id, paged


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
