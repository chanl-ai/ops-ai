"""Knowledge read through a connection's tools.

A "tool" source names a plugin's knowledge source: its list tool and its get tool, called through tools-service's
gateway like any agent's call. kb-service holds no token and loads no plugin code: tools-service signs each call with
the team's sign-in and sends it through the egress policy, and every page and fetch is in the call log. A sync lists
the changed items page by page from the last watermark, saving the cursor after each page, fetches only those whose
marker moved, and decides unchanged or next version by the content's digest. A full listing (the first, and weekly)
removes items the system no longer lists. Salesforce's rate limit ends the run partial and the next run resumes from
the saved page; a refused sign-in pauses the source until Test connection passes again. The listing and the paced
fetch are `ops_sources`, shared with every service that reads a source; this module is its knowledge state (the place
in the source's config, the held items as knowledge items) and what a fetched item becomes."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, cast

from pydantic import BaseModel, ConfigDict, TypeAdapter

from ops_service_kit.errors import ValidationFailed
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.ids import new_id
from ops_service_kit.narrow import a_list, an_object, as_json, json_object
from ops_sources import (
    AT_ONCE,
    FULL_EVERY,
    MAX_PAGES,
    Answer,
    Declared,
    Fetcher,
    FoundPlace,
    Held,
    Place,
    SourceTools,
    ToolReader,
    access_list,
    read_changes,
)
from ops_store import documents

from .ai import spent_on
from .files import FileNotScanned, Stored
from .origin import Origin, source_team
from .schemas import PreviewPage, Scope, ScopesPage, SourcePreview
from .settled import parse_error
from .store.knowledge import ItemFetched, ItemRow, RunError, RunWrite, SourceRow

if TYPE_CHECKING:
    from .service import KnowledgeService, Who

# The listing, its pacing and gone-twice live in ops_sources; kb-service reads them through its knowledge state.
# MAX_PAGES and FULL_EVERY are named here and read at each sync, so a test can shorten them for this service.
__all__ = ["FULL_EVERY", "MAX_PAGES", "Answer", "Declared", "ToolReader"]
TEAM_SIGN_IN = ("team",)


class Host(BaseModel):
    """One host a source's values would have its sync reach, as the account's egress rule answers for it."""

    model_config = ConfigDict(extra="ignore")

    host: str
    state: str
    reason: str | None = None
    runKey: str | None = None  # noqa: N815


HOSTS = TypeAdapter(list[Host])


class SourceConfig(TypedDict, total=False):
    """A tool source's stored `config`: what `source_config` wrote at create, and what each sync keeps between runs
    (where its listing got to, which items it saw and which it tombstoned). Every key is optional, since a source
    made before a key existed lacks it, and each declared type admits the null an older writer may have stored."""

    plugin: str | None
    source: str | None
    title: str | None
    listTool: str | None
    getTool: str | None
    changesTool: str | None
    scopesTool: str | None
    previewTool: str | None
    listsWhole: bool | None
    # Read with int(); a string or float an older writer stored still reads.
    fetchAtOnce: int | float | str | None
    site: bool | None
    getTakesTag: bool | None
    connectionId: str | None
    schedule: Json | None
    values: Json | None
    waitingHosts: JsonList | None
    # `needs_reconnect` while the connection refuses its sign-in; a bool from older writers.
    paused: bool | str | None
    lastFullAt: str | None
    watermark: JsonValue
    cursor: JsonValue
    changesCursor: JsonValue
    seenSoFar: list[str] | None
    tombstones: JsonValue
    repeats: JsonValue


# Read with the source row's `config`; a key holding another type fails the read (`StoredShapeError`).
SOURCE_CONFIG = documents.stored(SourceConfig)


def waiting_in(cfg: dict[str, JsonValue]) -> list[str]:
    """The hosts a source's config says wait on an admin's approval."""
    waiting = cfg.get("waitingHosts")
    return [str(w.get("host")) for w in waiting if isinstance(w, dict)] if isinstance(waiting, list) else []


class _PreviewRow(BaseModel):
    id: JsonValue = None
    outcome: str | None = None
    will_fetch: JsonValue = None


class _PreviewOut(BaseModel):
    found: int | None = None
    will_fetch: int | None = None
    pages: list[_PreviewRow] = []
    capped: JsonValue = None


def preview_of(output: JsonValue) -> SourcePreview:
    """What a plugin's preview tool answered, as the page the console shows."""
    out = _PreviewOut.model_validate(output or {})
    pages = [PreviewPage(id=str(p.id), outcome=p.outcome or "", will_fetch=bool(p.will_fetch)) for p in out.pages]
    return SourcePreview(
        found=out.found or len(pages),
        will_fetch=out.will_fetch or sum(p.will_fetch for p in pages),
        pages=pages,
        capped=bool(out.capped),
    )


def scopes_of(places: list[FoundPlace], following: str | None) -> ScopesPage:
    """The places a source's picker found, as the page the console shows."""
    scopes = [Scope(id=p.id, title=p.title, kind=p.kind, parent=p.parent, detail=p.detail) for p in places]
    return ScopesPage(scopes=scopes, next_cursor=following)


async def declared_sources(reader: ToolReader, tenant_id: str, team_id: str) -> list[Declared]:
    """Every knowledge source the team's apps declare."""
    return [Declared.model_validate(d) for d in await reader.declared(tenant_id, team_id)]


def refusal_of(found: Declared) -> tuple[str, str] | None:
    """Why a source declared for the team cannot be made, as (code, message), or None when it can. Create and the
    Add source list both ask this, so a source is offered exactly when create accepts it."""
    if not found.needsConnection:
        return None
    if not found.connectionId:
        return "connection_missing", f"{found.title} needs the team's connection; sign in first."
    if found.signIn not in TEAM_SIGN_IN:
        return (
            "sign_in_not_team",
            "This connection signs in each person. A knowledge source needs a team sign-in.",
        )
    return None


async def declared_source(reader: ToolReader | None, who: Who, plugin: str, name: str) -> Declared:
    """The plugin's knowledge source as tools-service declares it for the team: refused unless the plugin is on,
    names the source, and its connection signs in with the team's account, since a sync has no person behind it."""
    if reader is None:
        raise ValidationFailed(
            "This service reads no tools, so a tool source cannot be made.", code="tools_unavailable"
        )
    team = str(who.team_id or "")
    found = next(
        (d for d in await declared_sources(reader, who.tenant_id, team) if d.plugin == plugin and d.source == name),
        None,
    )
    if found is None:
        raise ValidationFailed(
            f"{plugin or 'That plugin'} offers no source {name or '?'} to this team; turn it on first."
        )
    if (refusal := refusal_of(found)) is not None:
        raise ValidationFailed(refusal[1], code=refusal[0])
    return found


async def source_config(reader: ToolReader | None, who: Who, wanted: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """A new tool source's config, from what tools-service declares for the team: refused unless the plugin is on,
    names the source, and its connection signs in with the team's account, since a sync has no person behind it.
    `wanted` names the plugin, its source and the source's own values."""
    plugin, name = str(wanted.get("plugin") or ""), str(wanted.get("source") or "")
    found = await declared_source(reader, who, plugin, name)
    cfg: dict[str, JsonValue] = {
        "plugin": plugin,
        "source": name,
        # The plugin's name for this kind of source, which the source shows as its kind.
        "title": found.title,
        "listTool": found.listTool,
        "getTool": found.getTool,
        "changesTool": found.changesTool,
        "scopesTool": found.scopesTool,
        "previewTool": found.previewTool,
        "listsWhole": found.listsWhole,
        "fetchAtOnce": found.fetchAtOnce or AT_ONCE,
        # Its items are a website's pages, so it starts with a website's cleaning and splitting.
        "site": found.site,
        "getTakesTag": found.getTakesTag,
        "connectionId": found.connectionId,
        "schedule": found.schedule or {"kind": "manual"},
        # What this source is set up with (start addresses, sites, spaces), checked against what the plugin declares
        # and sent to each of its tools as `source`.
        "values": source_values(found, wanted.get("values")),
    }
    return {**cfg, "waitingHosts": await waiting_hosts(cast(ToolReader, reader), who, cfg)}


async def waiting_hosts(reader: ToolReader, who: Who, cfg: dict[str, JsonValue]) -> list[JsonValue]:
    """The source's hosts an admin has yet to approve, each with the Security task it waits on: a sync reaches a
    source's own site only once the account lists its host, under the same rule as every new outside address. A host
    the account refuses refuses the source."""
    answers = HOSTS.validate_python(
        await reader.source_hosts(who.tenant_id, str(who.team_id or ""), cfg, credentials=who.credentials)
    )
    refused = [h for h in answers if h.state == "refused"]
    if refused:
        raise ValidationFailed(
            refused[0].reason or f"{refused[0].host} is not an allowed address.", code="egress_host_refused"
        )
    return [{"host": h.host, "runKey": h.runKey} for h in answers if h.state == "waiting"]


INPUT_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def source_values(declared: Declared, given: JsonValue) -> dict[str, JsonValue]:
    """A source's own settings checked against the inputs its plugin declares: a required one present, each of its
    declared type, and nothing undeclared."""
    inputs = declared.inputs
    values = given if isinstance(given, dict) else {}
    if unknown := sorted(set(values) - set(inputs)):
        raise ValidationFailed(f"{declared.title} takes no {', '.join(unknown)}.", code="invalid_source_values")
    for name, declared_input in inputs.items():
        if values.get(name) in (None, "", []):
            if declared_input.get("required", True):
                raise ValidationFailed(f"{declared.title} needs {name}.", code="invalid_source_values")
            continue
        expected = INPUT_TYPES.get(str(declared_input.get("type") or "string"), str)
        if not isinstance(values[name], expected):
            raise ValidationFailed(
                f"{name} is a {declared_input.get('type') or 'string'} for {declared.title}.",
                code="invalid_source_values",
            )
    return values


def _as_given(value: JsonValue) -> str | None:
    """A plugin's title or address stored as the plugin sent it, as it always was: a plugin declares both as text, and
    one that sends another kind has it kept, not dropped or rewritten."""
    return cast(str | None, value)


def _content(item: Json) -> bytes:
    content = str(item.get("content") or "")
    return base64.b64decode(content) if item.get("encoding") == "base64" else content.encode()


def _filename(item: Json) -> str:
    """The name the parser reads the type from: the title with the extension its mime gives."""
    ext = {"text/html": ".html", "text/plain": ".txt", "text/markdown": ".md", "application/pdf": ".pdf"}
    title = str(item.get("title") or item.get("id") or "item")
    suffix = ext.get(str(item.get("mime") or ""), "")
    return title if title.endswith(suffix) else f"{title}{suffix}"


def _place(cfg: SourceConfig) -> Place:
    """Where the source's listing got to, as its config holds it."""
    return Place(
        cursor=cfg.get("cursor"),
        watermark=cfg.get("watermark"),
        changes_cursor=cfg.get("changesCursor"),
        last_full_at=cfg.get("lastFullAt"),
        seen_so_far=list(cfg.get("seenSoFar") or []) if "seenSoFar" in cfg else None,
        tombstones=an_object(cfg.setdefault("tombstones", {}), "tombstones"),
        paused=cfg.get("paused"),
    )


def _keep(cfg: SourceConfig, place: Place) -> None:
    """The place written back into the source's config; a key with nothing to hold is left out, except the cursor,
    which a run that read a page keeps as null once its listing finished."""
    cfg["tombstones"] = place.tombstones
    if place.cursor is not None or "cursor" in cfg:
        cfg["cursor"] = place.cursor
    for key, value in (
        ("watermark", place.watermark),
        ("changesCursor", place.changes_cursor),
        ("lastFullAt", place.last_full_at),
        ("seenSoFar", place.seen_so_far),
        ("paused", place.paused),
    ):
        if value is None:
            cfg.pop(key, None)
        else:
            cfg[key] = value  # pyright: ignore[reportGeneralTypeIssues] - each key's value is its own declared type


class _KnowledgeState:
    """ops_sources' state port on a knowledge source: the place in the source's config, saved whole, and the held
    items as the source's knowledge items, read live so an item written earlier in the run answers as written."""

    def __init__(
        self, service: KnowledgeService, tenant: str, source_id: str, cfg: SourceConfig, known: dict[str, ItemRow]
    ) -> None:
        self.service, self.tenant, self.source_id, self.cfg, self.known = service, tenant, source_id, cfg, known

    def held(self, item_id: str) -> Held | None:
        i = self.known.get(item_id)
        if i is None:
            return None
        return Held(marker=i.marker, tag=i.tag, current=i.status == "indexed", gone_count=i.gone_count, title=i.title)

    async def save(self, place: Place) -> None:
        _keep(self.cfg, place)
        config = an_object(as_json(self.cfg), "source config")
        await self.service.store.update_source(self.tenant, self.source_id, {"config": config})

    async def mark(self, item_id: str, marker: str) -> None:
        await self.service.store.update_item(self.tenant, self.known[item_id].id, {"marker": marker})

    async def gone(self, item_id: str, count: int) -> None:
        await self.service.store.update_item(self.tenant, self.known[item_id].id, {"gone_count": count})


async def sync_tool_source(
    service: KnowledgeService,
    reader: ToolReader,
    who: Who,
    s: SourceRow,
    *,
    full: bool,
    trigger: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RunWrite:
    cfg = SOURCE_CONFIG(s.config or {})
    tenant, team, source_id = who.tenant_id, str(s.team_id), str(s.id)
    act = f"kb-sync:{source_id}"
    place = _place(cfg)
    known = {i.path: i for i in await service.store.items(tenant, source_ids=[source_id])}
    state = _KnowledgeState(service, tenant, source_id, cfg, known)
    tools = SourceTools.of(cfg)
    counts = {"listed": 0, "unchanged": 0, "upserted": 0, "deleted": 0, "failed": 0, "skipped": 0}
    listing = await read_changes(
        reader,
        state,
        place,
        tools,
        tenant=tenant,
        team=team,
        values=cfg.get("values"),
        connection_id=cfg.get("connectionId"),
        full=full,
        trigger=trigger,
        act=act,
        counts=counts,
        clock=clock,
        max_pages=MAX_PAGES,
        full_every=FULL_EVERY,
    )
    started, full, seen, log = listing.started, listing.full, listing.seen, listing.log
    errors = cast(list[RunError], listing.errors)
    status, stopped = listing.status, listing.stopped
    removed_at_source = listing.removed_at_source
    tombstones = place.tombstones
    gone = [i.path for i in known.values() if not i.parent_id] if full and listing.whole else []
    if status == "success" or listing.resumes:
        fetcher = Fetcher(reader, state, tools, listing, tenant=tenant, team=team, act=act)

        async def listed(r: Json, item: Json) -> None:
            # An item the listing already read (a crawl following links) is not fetched again.
            await _put(service, who, s, known, item, marker=str(r["marker"]), parent=None, counts=counts, errors=errors)

        async def fetched(r: Json, item: Json) -> None:
            await _put(service, who, s, known, item, marker=str(r["marker"]), parent=None, counts=counts, errors=errors)
            children = item.get("children")
            for child in (an_object(c, "child item") for c in (a_list(children, "children") if children else [])):
                kid_id = str(child["id"])
                seen.add(kid_id)
                marker = str(child.get("marker") or child.get("updated_at") or "")
                # An attachment is fetched only when its own marker moved, not each time its parent changes.
                ex = known.get(kid_id)
                if marker and ex is not None and ex.marker == marker and ex.status == "indexed":
                    counts["unchanged"] += 1
                    continue
                kid = await fetcher.fetch(kid_id)
                if kid.ok:
                    await _put(
                        service,
                        who,
                        s,
                        known,
                        an_object(kid.output, "fetched item"),
                        marker=marker,
                        parent=str(item["id"]),
                        counts=counts,
                        errors=errors,
                    )
                else:
                    counts["failed"] += 1

        done = await fetcher.fetch_changed(place, counts, listing.errors, log, on_listed=listed, on_fetched=fetched)
        if done.rate_limited:
            status = "partial"
        gone_now = done.gone_now
        # A base this source feeds may keep what its source removed: then it stays searchable and says so.
        keep = (await service.sync_rules(tenant, str(s.id)))["removedAtSource"] == "keep"
        if gone_now:
            gone_ids = [known[p].id for p in gone_now]
            gone_files = [known[p].file_id for p in gone_now]
            if keep:
                await _flag_removed(service, tenant, gone_ids)
                for p in gone_now:
                    tombstones.pop(p, None)
            else:
                counts["deleted"] += await service.store.remove_items(tenant, gone_ids)
                await release_snapshots(service, who, s, gone_files)
            done_with = "kept and flagged" if keep else "removed and tombstoned"
            log += [f"{known[p].title}: gone at the source twice, {done_with}" for p in gone_now]
        if removed_at_source:
            # Items the system says it deleted (in a changes listing) leave search at once, with their attachments.
            out_ids = [known[p].id for p in removed_at_source if p in known]
            out_ids += [i.id for i in known.values() if i.parent_id in set(out_ids)]
            files_out = [i.file_id for i in known.values() if i.id in set(out_ids)]
            if keep:
                await _flag_removed(service, tenant, out_ids)
            else:
                counts["deleted"] += await service.store.remove_items(tenant, out_ids)
                await release_snapshots(service, who, s, files_out)
            done_with = "kept and flagged" if keep else "removed"
            log += [f"{known[p].title}: deleted at the source, {done_with}" for p in removed_at_source if p in known]
        if full and not listing.resumes:
            dropped = [p for p in gone if p not in seen]
            removed_ids = [known[p].id for p in dropped]
            # Attachments go with their parent (parent_id holds the parent document's id).
            removed_ids += [i.id for i in known.values() if i.parent_id in set(removed_ids)]
            gone_files = [i.file_id for i in known.values() if i.id in set(removed_ids)]
            if keep:
                await _flag_removed(service, tenant, removed_ids)
            else:
                counts["deleted"] += await service.store.remove_items(tenant, removed_ids)
                await release_snapshots(service, who, s, gone_files)
            for p in dropped:
                log.append(
                    f"{known[p].title}: no longer listed by the system, {'kept and flagged' if keep else 'removed'}"
                )
        listing.settle(place, status)
    if stopped:
        log.append(stopped)
    await state.save(place)
    run_status = "partial" if status == "partial" else "failed" if status == "failed" else "success"
    if status == "skipped":
        run_status = "skipped"
    indexed = counts["upserted"] > 0 or counts["unchanged"] > 0
    await service.settle_run(who, s, run_status, activate=indexed)
    if counts["upserted"] or counts["deleted"]:
        _, by_source = await service._joined(tenant)  # pyright: ignore[reportPrivateUsage]
        await service.store.refreshed(tenant, by_source.get(source_id, []))
    spent_on(counts, log)
    run: RunWrite = {
        "tenant_id": tenant,
        "id": new_id("run"),
        "source_id": source_id,
        "trigger": trigger,
        "started_at": started,
        "duration_sec": round((clock() - started).total_seconds(), 2),
        "status": run_status,
        "counts": counts,
        "errors": errors,
        "log": log,
        "started_by": who.email,
    }
    await service.store.add_run(run)
    return run


async def _put(
    service: KnowledgeService,
    who: Who,
    s: SourceRow,
    known: dict[str, ItemRow],
    item: Json,
    *,
    marker: str,
    parent: str | None,
    counts: dict[str, int],
    errors: list[RunError],
) -> None:
    """One fetched item, kept as a knowledge snapshot in files-service before it is read, so a rebuild never fetches
    it again and a citation opens the copy used. Unchanged when files-service's digest of its bytes is the stored one
    (its marker updated); else read through the shared reading step and indexed as a new document or the next version
    of the one stored under the system's id. The snapshot an older version used is let go."""
    data = _content(item)
    item_id = str(item["id"])
    ex = known.get(item_id)
    tenant, team, source_id = who.tenant_id, source_team(s), str(s.id)
    name, mime = _filename(item), str(item.get("mime") or "text/plain")
    try:
        stored = await service.files.put(
            tenant, team, data, name=name, mime=mime, actor=f"kb-sync:{source_id}", purpose="knowledge_snapshot"
        )
        await service.files.use(tenant, team, stored.file_id, source_id=source_id, source_name=str(s.name))
    except (ValueError, FileNotScanned) as e:
        counts["failed"] += 1
        errors.append(
            {"itemTitle": _as_given(item.get("title")), "phase": "store", "errorClass": "snapshot", "message": str(e)}
        )
        return
    if ex is not None and ex.digest == stored.digest and ex.status == "indexed":
        await service.store.update_item(tenant, ex.id, {"marker": marker})
        counts["unchanged"] += 1
        return
    extra: ItemFetched = {
        "marker": marker,
        "parent_id": None,
        "url": _as_given(item.get("url")),
        "folder": str(item["folder"])[:400] if item.get("folder") else None,
        "fields": {str(k): str(v) for k, v in json_object(item.get("metadata")).items()} or None,
        "tag": str(item["marker"])[:200] if item.get("marker") else None,
        "gone_count": 0,
    }
    if parent is not None:
        parent_row = known.get(parent) or next(
            (i for i in await service.store.items(tenant, source_ids=[source_id]) if i.path == parent), None
        )
        extra["parent_id"] = parent_row.id if parent_row else None
    found = Stored(stored.file_id, name, stored.mime, stored.size, stored.digest, stored.deduplicated)
    origin = Origin(item_id, str(item.get("title") or item_id), extra, allowed=access_list(item) or None)
    done = await service._read_file(who, s, ex, name=name, found=found, rebuild=False, origin=origin)  # pyright: ignore[reportPrivateUsage]
    # The row as written, so a later look at this item in the run (its attachments, gone or removed) reads it.
    known[item_id] = (await service.store.items(tenant, item_id=done.id))[0]
    if ex is not None and ex.file_id and ex.file_id != stored.file_id:
        await release_snapshots(service, who, s, [ex.file_id])
    if done.status == "failed":
        counts["failed"] += 1
        errors.append(parse_error(done))
    elif done.status == "reading":
        counts.setdefault("reading", 0)
        counts["reading"] += 1
    elif done.unchanged:
        counts["unchanged"] += 1
    else:
        counts["upserted"] += 1


async def release_snapshots(service: KnowledgeService, who: Who, s: SourceRow, file_ids: list[str]) -> None:
    """Lets go of snapshots no item of the source uses any more; files-service keeps each for its retention days."""
    held = {i.file_id for i in await service.store.items(who.tenant_id, source_ids=[str(s.id)])}
    for file_id in dict.fromkeys(f for f in file_ids if f and f not in held):
        await service.files.release(who.tenant_id, source_team(s), file_id, source_id=str(s.id))


# What a kept item says once its source has removed it.
REMOVED_AT_SOURCE = "Removed at its source; kept because a knowledge base it feeds keeps removed items."


async def _flag_removed(service: KnowledgeService, tenant: str, item_ids: list[str]) -> None:
    """Items their source removed, kept searchable under a base's setting and marked so on the item."""
    for item_id in item_ids:
        await service.store.update_item(tenant, item_id, {"warning": REMOVED_AT_SOURCE})
