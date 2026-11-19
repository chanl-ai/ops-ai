"""`/v1/egress`: the tenant's egress allow-list. Admins add and remove hosts and private ranges; every change is
audited in the same transaction (`store.egress`). Anyone signed in reads the list; only an admin on the Security
team changes it."""

# No `from __future__ import annotations`: the `caller` dependency is a local of egress_router, and FastAPI resolves
# string annotations against module globals, where it does not exist.

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import Access, reader_of, require_provisioner
from ops_identity import CurrentService
from ops_identity.fastapi import Tx
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import Envelope, In, Json, ListResult, Out, error_responses, ok
from ops_service_kit.listing import ListQuery

from .callers import Person, person, security_admin
from .egress import EgressDenied, listable_host, listable_range
from .modules.schemas import ModuleRef
from .store import egress as stored
from .store.egress import EgressStore, HostInUseError


class EntryIn(In):
    value: str
    note: str = ""
    # Set only by the provisioner: the template slot the entry fills, and `system` to keep it from people.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None


class RemoveIn(In):
    value: str


class ListedHost(Out):
    host: str
    note: str
    added_by: str
    added_at: str
    # The tool sets whose endpoint is on the host, by id and the name a person knows them by.
    modules: list[ModuleRef]
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
    # An add returns the entry as its list shows it, so a screen can show the new row on whatever page it is on.
    entry: ListedHost | ListedRange | None = None


def _host_out(h: stored.ListedHost) -> Json:
    """A stored host row as the lists and an add return it."""
    return {
        "host": h.host,
        "note": h.note,
        "addedBy": h.added_by,
        "addedAt": h.added_at.isoformat(),
        "modules": [{"id": m.id, "name": m.name} for m in h.modules],
        "templateId": h.template_id,
        "protection": h.protection,
    }


def _range_out(x: stored.ListedRange) -> Json:
    """A stored range row as the list and an add return it."""
    return {
        "cidr": x.cidr,
        "note": x.note,
        "addedBy": x.added_by,
        "addedAt": x.added_at.isoformat(),
        "templateId": x.template_id,
        "protection": x.protection,
    }


class HeldHostDecisionIn(In):
    request_id: str
    host: str
    decision: Literal["approved", "rejected", "returned"]
    reason: str | None = None
    by: str | None = None


def egress_router(store: EgressStore) -> APIRouter:
    caller = person
    changer = security_admin

    r = APIRouter(prefix="/v1/egress", tags=["egress"], responses=error_responses())

    def _valid(kind: str, value: str) -> str:
        try:
            return listable_host(value) if kind == "host" else listable_range(value)
        except EgressDenied as e:
            raise ValidationFailed(str(e)) from e

    async def _listed(who: Person) -> tuple[list[Json], list[Json]]:
        listed = await store.allow_list(who.tenant_id)
        return [_host_out(h) for h in listed.hosts], [_range_out(x) for x in listed.ranges]

    @r.post("/held-hosts/decisions", response_model=Envelope[Change])
    async def decide_held_host(body: HeldHostDecisionIn, svc: CurrentService, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A Security admin's decision on a held host, sent by agents-service with its own token: a person
        decides in Human Tasks, never here. Approved lists the host, in the name of whoever approved it. The token must
        hold secrets_egress:manage, which only agents-service's scope cap allows (Settings.service_scopes)."""
        Access().can(svc, "secrets_egress", "manage", what="the allowed hosts")
        host = _valid("host", body.host)
        if body.decision != "approved":
            return ok({"kind": "host", "value": host, "changed": False})
        added = await store.add(
            svc.tenant_id,
            "host",
            host,
            actor=body.by or "Security",
            note=f"Approved in Human Tasks ({body.request_id})",
            at=datetime.now(UTC),
        )
        return ok({"kind": "host", "value": host, "changed": added})

    @r.get("", response_model=Envelope[AllowList], dependencies=[Depends(reader_of("secrets_egress"))])
    async def allow_list(who: Annotated[Person, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        hosts, ranges = await _listed(who)
        return ok({"hosts": hosts, "ranges": ranges})

    @r.get("/hosts", response_model=Envelope[HostList], dependencies=[Depends(reader_of("secrets_egress"))])
    async def list_hosts(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Person, Depends(caller)], _: Tx, q: ListQuery
    ) -> JSONResponse:
        """The hosts, by name, a page at a time on the shared list contract; `search` matches the host or its note,
        `ids` names hosts, and the filter `templateId` keeps the hosts filling those template slots."""
        page, hosts = await store.host_page(who.tenant_id, q)
        return ok({**page, "data": [_host_out(h) for h in hosts]})

    async def _add(kind: str, body: EntryIn, who: Person) -> JSONResponse:
        value = _valid(kind, body.value)
        template = {k: v for k, v in (("template_id", body.template_id), ("protection", body.protection)) if v}
        if template and who.principal is not None:
            require_provisioner(who.principal, "secrets_egress")
        changed = await store.add(
            who.tenant_id, kind, value, actor=who.name, note=body.note.strip(), at=datetime.now(UTC), template=template
        )
        row = await store.entry(who.tenant_id, kind, value)
        entry = None if row is None else _host_out(row) if isinstance(row, stored.ListedHost) else _range_out(row)
        return ok({"kind": kind, "value": value, "changed": changed, "entry": entry}, 201 if changed else 200)

    async def _remove(kind: str, body: RemoveIn, who: Person) -> JSONResponse:
        value = _valid(kind, body.value)
        if who.principal is not None:
            # A `system` entry is the provisioner's: no person removes it, a Security admin included.
            protection = await store.protection(who.tenant_id, kind, value)
            Access().can(
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

    @r.post(
        "/hosts",
        response_model=Envelope[Change],
        status_code=201,
        responses={200: {"model": Envelope[Change], "description": "Already listed; nothing was written"}},
    )
    async def add_host(body: EntryIn, who: Annotated[Person, Depends(changer)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _add("host", body, who)

    @r.post("/hosts/remove", response_model=Envelope[Change])
    async def remove_host(body: RemoveIn, who: Annotated[Person, Depends(changer)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _remove("host", body, who)

    @r.post(
        "/ranges",
        response_model=Envelope[Change],
        status_code=201,
        responses={200: {"model": Envelope[Change], "description": "Already listed; nothing was written"}},
    )
    async def add_range(body: EntryIn, who: Annotated[Person, Depends(changer)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _add("range", body, who)

    @r.post("/ranges/remove", response_model=Envelope[Change])
    async def remove_range(body: RemoveIn, who: Annotated[Person, Depends(changer)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return await _remove("range", body, who)

    return r
