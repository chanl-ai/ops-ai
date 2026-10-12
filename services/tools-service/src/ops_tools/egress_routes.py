"""`/v1/egress`: the tenant's egress allow-list. Admins add and remove hosts and private ranges; every change is
audited in the same transaction (`store.egress`). Until ops_identity resolves roles (c-006), every caller of this
dev service may edit the list."""

# No `from __future__ import annotations`: the `caller` dependency is a local of egress_router, and FastAPI resolves
# string annotations against module globals, where it does not exist.

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Envelope, Out, error_responses, ok

from .callers import Person, person
from .egress import EgressDenied, listable_host, listable_range
from .store.egress import EgressStore, HostInUseError


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class EntryIn(_In):
    value: str
    note: str = ""


class RemoveIn(_In):
    value: str


class ListedHost(Out):
    host: str
    note: str
    added_by: str
    added_at: str
    modules: list[str]


class ListedRange(Out):
    cidr: str
    note: str
    added_by: str
    added_at: str


class AllowList(Out):
    hosts: list[ListedHost]
    ranges: list[ListedRange]


class Change(Out):
    kind: Literal["host", "range"]
    value: str
    changed: bool


def _operation_id(route: APIRoute) -> str:
    return f"egress_{route.name}"


def egress_router(store: EgressStore) -> APIRouter:
    caller = person

    r = APIRouter(
        prefix="/v1/egress", tags=["egress"], responses=error_responses(), generate_unique_id_function=_operation_id
    )

    def _valid(kind: str, value: str) -> str:
        try:
            return listable_host(value) if kind == "host" else listable_range(value)
        except EgressDenied as e:
            raise ValidationFailed(str(e)) from e

    @r.get("", response_model=Envelope[AllowList])
    async def allow_list(who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        listed = await store.allow_list(who.tenant_id)
        stamp = {"hosts": listed["hosts"], "ranges": listed["ranges"]}
        for rows in stamp.values():
            for row in rows:
                row["added_at"] = row["added_at"].isoformat()
        hosts = [
            {
                "host": h["host"],
                "note": h["note"],
                "addedBy": h["added_by"],
                "addedAt": h["added_at"],
                "modules": h["modules"],
            }
            for h in stamp["hosts"]
        ]
        ranges = [
            {"cidr": x["cidr"], "note": x["note"], "addedBy": x["added_by"], "addedAt": x["added_at"]}
            for x in stamp["ranges"]
        ]
        return ok({"hosts": hosts, "ranges": ranges})

    async def _add(kind: str, body: EntryIn, who: Person) -> JSONResponse:
        value = _valid(kind, body.value)
        changed = await store.add(
            who.tenant_id, kind, value, actor=who.name, note=body.note.strip(), at=datetime.now(UTC)
        )
        return ok({"kind": kind, "value": value, "changed": changed}, 201 if changed else 200)

    async def _remove(kind: str, body: RemoveIn, who: Person) -> JSONResponse:
        value = _valid(kind, body.value)
        try:
            removed = await store.remove(who.tenant_id, kind, value, actor=who.name, at=datetime.now(UTC))
        except HostInUseError as e:
            raise Conflict(
                f"{e.host} is called by {', '.join(e.modules)}. Change those modules first.",
                details={"modules": e.modules},
            ) from e
        if not removed:
            raise NotFound(f"{value} on the egress allow-list")
        return ok({"kind": kind, "value": value, "changed": True})

    @r.post("/hosts", response_model=Envelope[Change], status_code=201)
    async def add_host(body: EntryIn, who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _add("host", body, who)

    @r.post("/hosts/remove", response_model=Envelope[Change])
    async def remove_host(body: RemoveIn, who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _remove("host", body, who)

    @r.post("/ranges", response_model=Envelope[Change], status_code=201)
    async def add_range(body: EntryIn, who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _add("range", body, who)

    @r.post("/ranges/remove", response_model=Envelope[Change])
    async def remove_range(body: RemoveIn, who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _remove("range", body, who)

    return r
