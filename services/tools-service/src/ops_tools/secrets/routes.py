"""`/v1/secrets`: create, rotate, delete and list tool secrets. A value goes in and never comes out: responses
carry a secret's name, version and times only. Until ops_identity resolves roles (c-006), every caller of this dev
service may manage secrets."""

# No `from __future__ import annotations`: the `caller` dependency is a local of secrets_router, and FastAPI resolves
# string annotations against module globals, where it does not exist.

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.http import Envelope, Out, error_responses, ok

from ..callers import Person, person
from ..store.secrets import SecretStore
from .cipher import Cipher, context_of


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class SecretIn(_In):
    name: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    value: str = Field(min_length=1, max_length=8192)


class RotateIn(_In):
    value: str = Field(min_length=1, max_length=8192)


class SecretMeta(Out):
    name: str
    version: int
    created_by: str
    created_at: str
    rotated_at: str | None = None
    last_used_at: str | None = None


def _meta(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "name": row["name"],
        "version": row["version"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"].isoformat(),
    }
    for key, col in (("rotatedAt", "rotated_at"), ("lastUsedAt", "last_used_at")):
        if row.get(col):
            out[key] = row[col].isoformat()
    return out


def _operation_id(route: APIRoute) -> str:
    return f"secrets_{route.name}"


def secrets_router(store: SecretStore, cipher: Cipher) -> APIRouter:
    caller = person

    r = APIRouter(
        prefix="/v1/secrets", tags=["secrets"], responses=error_responses(), generate_unique_id_function=_operation_id
    )

    async def _one(who: Person, name: str) -> dict[str, Any]:
        row = next((x for x in await store.listed(who.tenant_id) if x["name"] == name), None)
        if row is None:
            raise NotFound(f"Secret {name}")
        return _meta(row)

    @r.get("", response_model=Envelope[list[SecretMeta]])
    async def list_secrets(who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok([_meta(x) for x in await store.listed(who.tenant_id)])

    @r.post("", response_model=Envelope[SecretMeta], status_code=201)
    async def create_secret(body: SecretIn, who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        blob = cipher.encrypt(body.value, context=context_of(who.tenant_id, body.name))
        if not await store.create(who.tenant_id, body.name, blob, actor=who.name, at=datetime.now(UTC)):
            raise Conflict(f"A secret named {body.name} already exists. Rotate it to change its value.")
        return ok(await _one(who, body.name), 201)

    @r.post("/{name}/rotate", response_model=Envelope[SecretMeta])
    async def rotate_secret(name: str, body: RotateIn, who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        blob = cipher.encrypt(body.value, context=context_of(who.tenant_id, name))
        if await store.rotate(who.tenant_id, name, blob, actor=who.name, at=datetime.now(UTC)) is None:
            raise NotFound(f"Secret {name}")
        return ok(await _one(who, name))

    @r.delete("/{name}", status_code=204, response_class=Response)
    async def delete_secret(name: str, who: Annotated[Person, Depends(caller)]) -> Response:  # pyright: ignore[reportUnusedFunction]
        if not await store.delete(who.tenant_id, name, actor=who.name, at=datetime.now(UTC)):
            raise NotFound(f"Secret {name}")
        return Response(status_code=204)

    return r
