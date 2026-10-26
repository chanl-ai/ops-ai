"""`/v1/egress`: the tenant's egress allow-list. Admins add and remove hosts and private ranges; every change is
audited in the same transaction (`store.egress`). Anyone signed in reads the list; only an admin on the Security
team changes it."""

# No `from __future__ import annotations`: the `caller` dependency is a local of egress_router, and FastAPI resolves
# string annotations against module globals, where it does not exist.

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_access import Access, require_provisioner
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Envelope, ListResult, Out, error_responses, ok, page_window, paged
from ops_service_kit.settings import Settings

from .callers import Person, person, security_admin
from .egress import EgressDenied, listable_host, listable_range
from .store.egress import EgressStore, HostInUseError


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class EntryIn(_In):
    value: str
    note: str = ""
    # Set only by the provisioner (c-180): the template slot the entry fills, and `system` to keep it from people.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class RemoveIn(_In):
    value: str


class ListedHost(Out):
    host: str
    note: str
    added_by: str
    added_at: str
    modules: list[str]
    template_id: str | None = None
    protection: Literal["system", "managed"] | None = None


class ListedRange(Out):
    cidr: str
    note: str
    added_by: str
    added_at: str
    template_id: str | None = None
    protection: Literal["system", "managed"] | None = None


class AllowList(Out):
    hosts: list[ListedHost]
    ranges: list[ListedRange]


class HostList(ListResult[ListedHost]):
    """GET /v1/egress/hosts: one page of the listed hosts."""


class Change(Out):
    kind: Literal["host", "range"]
    value: str
    changed: bool


def egress_router(store: EgressStore, *, security_team: str | None = None) -> APIRouter:
    caller = person
    team = security_team or Settings().security_team_id
    changer = security_admin(team)

    r = APIRouter(prefix="/v1/egress", tags=["egress"], responses=error_responses())

    def _valid(kind: str, value: str) -> str:
        try:
            return listable_host(value) if kind == "host" else listable_range(value)
        except EgressDenied as e:
            raise ValidationFailed(str(e)) from e

    async def _listed(who: Person) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        listed = await store.allow_list(who.tenant_id)
        stamp = {"hosts": listed["hosts"], "ranges": listed["ranges"]}
        for rows in stamp.values():
            for row in rows:
                row["added_at"] = row["added_at"].isoformat()
        hosts: list[dict[str, object]] = [
            {
                "host": h["host"],
                "note": h["note"],
                "addedBy": h["added_by"],
                "addedAt": h["added_at"],
                "modules": h["modules"],
                "templateId": h.get("template_id"),
                "protection": h.get("protection"),
            }
            for h in stamp["hosts"]
        ]
        ranges: list[dict[str, object]] = [
            {
                "cidr": x["cidr"],
                "note": x["note"],
                "addedBy": x["added_by"],
                "addedAt": x["added_at"],
                "templateId": x.get("template_id"),
                "protection": x.get("protection"),
            }
            for x in stamp["ranges"]
        ]
        return hosts, ranges

    @r.get("", response_model=Envelope[AllowList])
    async def allow_list(who: Annotated[Person, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        hosts, ranges = await _listed(who)
        return ok({"hosts": hosts, "ranges": ranges})

    @r.get("/hosts", response_model=Envelope[HostList])
    async def list_hosts(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Person, Depends(caller)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
        search: str = "",
        template_id: Annotated[str | None, Query(alias="templateId")] = None,
    ) -> JSONResponse:
        """The hosts, by name, a page at a time; `search` matches the host or its note, `templateId` the template slot
        a provisioned host fills (c-180). The page and its count are queried, not sliced."""
        total = await store.hosts_count(who.tenant_id, search, template_id)
        page, offset = page_window(total, page, page_size)
        rows = await store.hosts_page(who.tenant_id, search, offset, page_size, template_id)
        hosts = [
            {
                "host": h["host"],
                "note": h["note"],
                "addedBy": h["added_by"],
                "addedAt": h["added_at"].isoformat(),
                "modules": h["modules"],
                "templateId": h.get("template_id"),
                "protection": h.get("protection"),
            }
            for h in rows
        ]
        return ok(paged(hosts, total, page, page_size))

    async def _add(kind: str, body: EntryIn, who: Person) -> JSONResponse:
        value = _valid(kind, body.value)
        template = {k: v for k, v in (("template_id", body.template_id), ("protection", body.protection)) if v}
        if template and who.principal is not None:
            require_provisioner(who.principal, "secrets_egress")
        changed = await store.add(
            who.tenant_id, kind, value, actor=who.name, note=body.note.strip(), at=datetime.now(UTC), template=template
        )
        return ok({"kind": kind, "value": value, "changed": changed}, 201 if changed else 200)

    async def _remove(kind: str, body: RemoveIn, who: Person) -> JSONResponse:
        value = _valid(kind, body.value)
        if who.principal is not None:
            # A `system` entry is the provisioner's: no person removes it, a Security admin included (c-180).
            protection = await store.protection(who.tenant_id, kind, value)
            Access(security_team=team).can(
                who.principal, "secrets_egress", "manage", what=value, code="not_security_admin", protection=protection
            )
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
    async def add_host(body: EntryIn, who: Annotated[Person, Depends(changer)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _add("host", body, who)

    @r.post("/hosts/remove", response_model=Envelope[Change])
    async def remove_host(body: RemoveIn, who: Annotated[Person, Depends(changer)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _remove("host", body, who)

    @r.post("/ranges", response_model=Envelope[Change], status_code=201)
    async def add_range(body: EntryIn, who: Annotated[Person, Depends(changer)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _add("range", body, who)

    @r.post("/ranges/remove", response_model=Envelope[Change])
    async def remove_range(body: RemoveIn, who: Annotated[Person, Depends(changer)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _remove("range", body, who)

    return r
