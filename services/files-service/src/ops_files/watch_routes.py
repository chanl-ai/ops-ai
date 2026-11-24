# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The watched folders routes (`/v1/watches`): which folders of an app a team copies into Files, Check now, and what
each check found.

Every member reads the team's watches and their events with files.view; adding, changing, checking and deleting one
needs watches.manage (Admin and Builder by default), since a watch copies a folder into Files for every member while
the source's own access list is not applied. Each change writes an audit entry naming the folders, in the change's
transaction. A service holding files:view reads the watches and events of the team its token names (agents-service's
Files changed trigger). Another team's watch is 404 on every route."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import Field, JsonValue

from ops_access import can
from ops_files.app import Caller, service_scope
from ops_files.store import WatchesStore, WatchRow
from ops_files.store.watches import Audit, EventRow
from ops_files.tenant_files import Who
from ops_files.watch_uses import Used, WatchUses
from ops_identity import CurrentCaller, CurrentPrincipal
from ops_identity.fastapi import Tx
from ops_service_kit.errors import Conflict, Forbidden, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import Envelope, In, ListResult, Option, OptionsPage, Out, ok, options_window
from ops_service_kit.ids import new_id
from ops_service_kit.listing import ListQuery
from ops_sources import Declared, Reader, refusal_of, source_values

# A watch's settings as the source's picker saved them (site, libraries, folders); kept small, as a knowledge
# source's are.
VALUES_MAX = 50
# Names kept per input for its picked places.
NAMES_MAX = 200

# {input: {id: name}}: what the picker called each place it saved in `values`, so the list names them.
PickedNames = dict[str, Annotated[dict[str, Annotated[str, Field(max_length=300)]], Field(max_length=NAMES_MAX)]]


async def watch_manager(p: CurrentPrincipal) -> Who:
    """watches.manage in the team the person acts in; a service never adds or checks a watch."""
    if p.kind == "service":
        raise Forbidden("Only a person adds, changes, checks or deletes a watched folder.", code="scope_required")
    if not p.team_id:
        raise Forbidden("Choose a team to work with watched folders in.", code="team_required")
    can(p, "watches", "manage", team=p.team_id, what="watched folders")
    return Who(tenant_id=p.tenant_id, team=p.team_id, actor=p.email or p.sub)


Manager = Annotated[Who, Depends(watch_manager)]

# The scope a service holds to ask a check: agents-service's Files changed trigger, on its schedule.
CHECK_SCOPE = "files:check"


async def check_asker(p: CurrentCaller) -> Who:
    """A person with watches.manage, or a service holding files:check for the team its token names. files:check is a
    service scope with no cell, so it is read from the token here rather than through `can()`."""
    if p.kind != "service":
        return await watch_manager(p)
    if CHECK_SCOPE not in p.scopes:
        raise Forbidden(f"This service token does not hold the {CHECK_SCOPE} scope.", code="scope_required")
    if not p.tenant_id or not p.team_id:
        raise Forbidden("A service token asking a check names its tenant and team.", code="team_required")
    return Who(tenant_id=p.tenant_id, team=p.team_id, actor=p.sub)


Asker = Annotated[Who, Depends(check_asker)]


class CheckIn(In):
    # Who asked, as the audit entry names it; read only from a service (a trigger names itself), a person is named
    # by their sign-in.
    by: str | None = Field(default=None, max_length=200)


class WatchIn(In):
    name: str = Field(min_length=1, max_length=200)
    plugin: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1, max_length=120)
    # The app connection the source reads through, as Add source's kinds name it; part of each file's identity. The
    # watch takes the team's connection for the app; one given must be it, and left out it is filled in.
    connection_id: str | None = Field(default=None, max_length=64)
    values: dict[str, JsonValue] = Field(max_length=VALUES_MAX)
    names: PickedNames = Field(default_factory=dict, max_length=VALUES_MAX)


class WatchChange(In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    values: dict[str, JsonValue] | None = Field(default=None, max_length=VALUES_MAX)
    # Replaces the kept names when given; left out, the kept names still label the ids that remain.
    names: PickedNames | None = Field(default=None, max_length=VALUES_MAX)


class FailedFile(Out):
    path: str | None
    size: int | None
    reason: str | None
    # too_large (no retry brings it in) or fetch_failed; null on outcomes written before codes were kept.
    code: str | None = None


class LastCheck(Out):
    """What the last check ended as: success, partial, refused or failed, with what it brought in and why it
    stopped; `failures` names the first failed files."""

    status: str
    brought: int = 0
    failed: int = 0
    removed: int = 0
    stopped: str = ""
    # Why a refused or partial check stopped: needs_reconnect, unreachable, not_installed, app_off, rate_limited,
    # fetch_failed, continues, list_failed, lease_lost; empty on a success. The console words its alert from it.
    code: str = ""
    failures: list[FailedFile] = Field(default_factory=list[FailedFile])


class Folder(Out):
    """One picked place of a watch: the input it was picked for, the source's id, and the name the picker showed
    (the id when none was kept)."""

    input: str
    id: str
    name: str


class UsedBy(Out):
    workflow_id: str
    name: str
    live: bool


class WatchView(Out):
    id: str
    name: str
    plugin: str
    source: str
    connection_id: str | None
    values: dict[str, JsonValue]
    # The picked places by name, for the inputs the picker named; inputs with no picker (path patterns) are not
    # listed, and a watch saved without names (the SDK and CLI) has none, so a screen counts `values` instead.
    folders: list[Folder]
    # The watch's files in Files now (entries not removed at the source).
    files_in_files: int
    # The newest event's number, 0 when none, so a reader of the events knows where they end.
    last_event: int
    # A workflow's Files changed trigger names it, so Stop watching is refused; false when agents-service could
    # not be asked.
    in_use: bool
    used_by: list[UsedBy]
    created_by: str
    created_at: datetime
    updated_at: datetime
    # A check is asked for or running: Check now answers "already checking" until it ends.
    checking: bool
    last_check_at: datetime | None
    last_check: LastCheck | None


class WatchEventView(Out):
    number: int
    file_id: str | None
    version: int | None
    kind: str
    reason: str | None
    # Why a failed event failed: too_large or fetch_failed; null for other kinds.
    code: str | None = None
    size: int | None
    path: str | None
    at: datetime
    # A new file that is a removed one moved or renamed at the source: that entry and where it was.
    linked_file_id: str | None = None
    linked_path: str | None = None


class WatchEvents(Out):
    """Events after `after`, oldest first; `next_after` asks for the next page, None at the end."""

    data: list[WatchEventView]
    next_after: int | None


class CheckAsked(Out):
    status: Literal["asked"]


def _view(w: WatchRow, now: datetime, used: Used | None = None) -> WatchView:
    by = [UsedBy.model_validate(u) for u in (used or {}).get(w.id, [])]
    running = w.lease_until is not None and w.lease_until.replace(tzinfo=w.lease_until.tzinfo or UTC) > now
    return WatchView(
        id=w.id,
        name=w.name,
        plugin=w.plugin,
        source=w.source,
        connection_id=w.connection_id,
        values=w.values,
        folders=_named(w.values, w.value_names or {}),
        files_in_files=w.files_in_files,
        last_event=w.next_event - 1,
        in_use=bool(by),
        used_by=by,
        created_by=w.created_by,
        created_at=w.created_at,
        updated_at=w.updated_at,
        checking=w.check_requested_at is not None or running,
        last_check_at=w.last_check_at,
        last_check=LastCheck.model_validate(w.last_outcome) if w.last_outcome else None,
    )


def _named(values: dict[str, JsonValue], names: dict[str, dict[str, str]]) -> list[Folder]:
    """Each picked id of the inputs the picker named, with its kept name; an id picked later and never named shows
    as itself."""
    out: list[Folder] = []
    for field, labels in names.items():
        picked = values.get(field)
        for one in picked if isinstance(picked, list) else [picked] if isinstance(picked, str) else []:
            if isinstance(one, str) and one:
                out.append(Folder(input=field, id=one, name=labels.get(one, one)))
    return out


def _kept(names: dict[str, dict[str, str]], values: dict[str, JsonValue]) -> dict[str, dict[str, str]]:
    """Only the names of ids the values pick, so a name the picker showed for a place left unpicked is not kept."""
    out: dict[str, dict[str, str]] = {}
    for field, labels in names.items():
        picked = values.get(field)
        ids = {x for x in (picked if isinstance(picked, list) else [picked]) if isinstance(x, str)}
        out[field] = {k: v for k, v in labels.items() if k in ids}
    return out


def _folders(values: dict[str, JsonValue]) -> JsonValue:
    """The places a watch copies, as the audit entry names them."""
    return {k: v for k, v in values.items() if isinstance(v, str | list)}


def watches_router(
    store: WatchesStore,
    *,
    reader: Reader | None,
    uses: WatchUses | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:
    """Mounted by `create_files_app`, which imports this module when it builds the app (this one reads its `who`).
    `reader` reads the sources the team's apps declare, which a watch's plugin, source and folders are checked
    against, as a knowledge source's are."""
    router = APIRouter(prefix="/v1/watches", tags=["watches"])

    async def declared(who: Who, plugin: str, source: str) -> Declared:
        """The plugin's folder source as tools-service declares it for the team: refused unless the plugin is on,
        names a source Files can watch, and its connection signs in with the team's account, since a check has no
        person behind it."""
        if reader is None:
            raise ValidationFailed("Files reads no apps here, so a folder cannot be watched.", code="tools_unavailable")
        rows = await reader.declared(who.tenant_id, who.team)
        found = next(
            (Declared.model_validate(d) for d in rows if (d.get("plugin"), d.get("source")) == (plugin, source)), None
        )
        if found is None or not found.files:
            raise ValidationFailed(
                f"{plugin} offers no folders for Files to watch in this team; turn it on first.",
                code="source_not_offered",
            )
        if (refusal := refusal_of(found)) is not None:
            raise ValidationFailed(refusal[1], code=refusal[0])
        return found

    async def used(who: Who, ids: list[str]) -> Used | None:
        """Which workflows name each watch; {} with no agents-service, None when it could not be asked."""
        if uses is None or not ids:
            return {}
        return await uses.of(who.tenant_id, who.team, ids)

    # Read routes are open to services holding files:view, for the team their token names.
    view_scope = service_scope("view")

    async def found(watch_id: str) -> WatchRow:
        w = await store.get(watch_id)
        if w is None:
            raise NotFound("watched folder")
        return w

    @router.get("", response_model=Envelope[ListResult[WatchView]], dependencies=[view_scope])
    async def list_watches(who: Caller, _: Tx, q: ListQuery) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The team's watched folders by name, each with its last check and whether one is running."""
        now = clock()
        rows, page = await store.list(who.team, q)
        named = await used(who, [w.id for w in rows])
        data = [_view(w, now, named).model_dump(mode="json", by_alias=True) for w in rows]
        return ok({"data": data, "pagination": page["pagination"], "facets": page["facets"]})

    @router.get("/options", response_model=Envelope[OptionsPage], dependencies=[view_scope])
    async def watch_options(  # pyright: ignore[reportUnusedFunction]
        who: Caller,
        _: Tx,
        search: str = "",
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        ids: Annotated[list[str] | None, Query()] = None,
    ) -> JSONResponse:
        """The team's watches a picker offers (the Files changed trigger), searched and paged in the query."""
        offset, rows = options_window(cursor, limit)
        found_rows = await store.options(who.team, search=search, offset=offset, limit=rows, ids=ids)
        more = len(found_rows) > limit and ids is None
        page = OptionsPage(
            data=[Option(id=i, label=n) for i, n in found_rows[:limit]],
            next_cursor=str(offset + limit) if more else None,
        )
        return ok(page.model_dump(mode="json", by_alias=True))

    @router.post("", status_code=201, response_model=Envelope[WatchView])
    async def create_watch(body: WatchIn, who: Manager) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Watches an app's folders; nothing is copied until the first check (Check now, or a trigger's schedule). The
        plugin, source and folders are checked against what the team's apps declare, and the watch reads through the
        team's connection for that app."""
        found = await declared(who, body.plugin, body.source)
        values = source_values(found, body.values)
        if body.connection_id and body.connection_id != found.connectionId:
            raise ValidationFailed(f"That is not the team's {found.title} connection.", code="connection_mismatch")
        at = clock()
        audit: Audit = {
            "actor": who.actor,
            "action": "files.watch.created",
            "summary": f"Watched {body.name} from {body.plugin} in Files",
            "detail": {"plugin": body.plugin, "source": body.source, "folders": _folders(body.values)},
        }
        w = await store.create(
            {
                "tenant_id": who.tenant_id,
                "id": new_id("wat"),
                "team": who.team,
                "name": body.name,
                "plugin": body.plugin,
                "source": body.source,
                "connection_id": found.connectionId,
                "values": values,
                "value_names": _kept(body.names, values),
                "created_by": who.actor,
                "created_at": at,
            },
            audit=audit,
        )
        return ok(_view(w, at).model_dump(mode="json", by_alias=True), 201)

    @router.get("/{watch_id}", response_model=Envelope[WatchView], dependencies=[view_scope])
    async def get_watch(watch_id: str, who: Caller, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        w = await found(watch_id)
        return ok(_view(w, clock(), await used(who, [w.id])).model_dump(mode="json", by_alias=True))

    @router.patch("/{watch_id}", response_model=Envelope[WatchView])
    async def change_watch(watch_id: str, body: WatchChange, who: Manager) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Renames the watch or changes its folders; new folders are listed whole on the next check."""
        before = await found(watch_id)
        if body.values is not None:
            source_values(await declared(who, before.plugin, before.source), body.values)
        at = clock()
        audit: Audit = {
            "actor": who.actor,
            "action": "files.watch.changed",
            "summary": f"Changed the watched folder {body.name or before.name}",
            "detail": {
                "name": body.name,
                "folders": _folders(body.values) if body.values is not None else None,
                "foldersBefore": _folders(before.values),
            },
        }
        names = None if body.names is None else _kept(body.names, body.values or before.values)
        if not await store.change(watch_id, name=body.name, values=body.values, names=names, at=at, audit=audit):
            raise NotFound("watched folder")
        return ok(_view(await found(watch_id), at).model_dump(mode="json", by_alias=True))

    @router.delete("/{watch_id}", status_code=204, response_class=Response)
    async def delete_watch(watch_id: str, who: Manager) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Stops watching; the files already brought in stay in Files under their own retention. Refused while a
        workflow's Files changed trigger names the watch, and when agents-service cannot say whether one does."""
        before = await found(watch_id)
        named = await used(who, [watch_id])
        if named is None:
            raise ServiceUnavailable("Files could not ask which workflows use this folder; try again shortly.")
        if by := named.get(watch_id):
            names = ", ".join(str(u.get("name")) for u in by[:3])
            raise Conflict(
                f"A workflow uses this folder: {names}. Remove its Files changed trigger first.",
                code="watch_in_use",
                details={"usedBy": [dict(u) for u in by]},
            )
        audit: Audit = {
            "actor": who.actor,
            "action": "files.watch.deleted",
            "summary": f"Stopped watching {before.name}",
            "detail": {"plugin": before.plugin, "folders": _folders(before.values)},
        }
        if not await store.delete(watch_id, audit=audit):
            raise NotFound("watched folder")
        return Response(status_code=204)

    @router.post("/{watch_id}/check", status_code=202, response_model=Envelope[CheckAsked])
    async def check_watch(  # pyright: ignore[reportUnusedFunction]
        watch_id: str, who: Asker, p: CurrentCaller, body: CheckIn | None = None
    ) -> JSONResponse:
        """Check now, by a person or a Files changed trigger's schedule: the background process checks the watch
        within seconds. 409 `already_checking` while a check is asked for or running."""
        w = await found(watch_id)
        actor = (body.by if body and body.by and p.kind == "service" else None) or who.actor
        audit: Audit = {
            "actor": actor,
            "action": "files.watch.checked",
            "summary": f"Asked for a check of {w.name}",
            "detail": {"folders": _folders(w.values)},
        }
        if not await store.request_check(watch_id, clock(), audit=audit):
            raise Conflict("A check of this folder is already running.", code="already_checking")
        return ok(CheckAsked(status="asked").model_dump(mode="json", by_alias=True), 202)

    @router.get("/{watch_id}/events", response_model=Envelope[WatchEvents], dependencies=[view_scope])
    async def watch_events(  # pyright: ignore[reportUnusedFunction]
        watch_id: str,
        who: Caller,
        _: Tx,
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> JSONResponse:
        """What the watch's checks found (new, changed, renamed, removed, failed) after event `after`, oldest first."""
        del who
        await found(watch_id)
        rows: list[EventRow] = await store.events(watch_id, after=after, limit=limit + 1)
        page = WatchEvents(
            data=[
                WatchEventView.model_validate(r.model_dump(exclude={"tenant_id", "team", "watch_id"}))
                for r in rows[:limit]
            ],
            next_after=rows[limit - 1].number if len(rows) > limit else None,
        )
        return ok(page.model_dump(mode="json", by_alias=True))

    return router


__all__ = ["WatchView", "watch_manager", "watches_router"]
