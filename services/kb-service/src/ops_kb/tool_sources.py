"""Knowledge read through a connection's tools.

A "tool" source names a plugin's knowledge source: its list tool and its get tool, called through tools-service's
gateway like any agent's call. kb-service holds no token and loads no plugin code: tools-service signs each call with
the team's sign-in and sends it through the egress policy, and every page and fetch is in the call log. A sync lists
the changed items page by page from the last watermark, saving the cursor after each page, fetches only those whose
marker moved, and decides unchanged or next version by the content's digest. A full listing (the first, and weekly)
removes items the system no longer lists. Salesforce's rate limit ends the run partial and the next run resumes from
the saved page; a refused sign-in pauses the source until Test connection passes again."""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import Conflict, ValidationFailed
from ops_service_kit.ids import new_id

from .ai import spent_on
from .files import FileNotScanned, Stored
from .origin import Origin, source_team

if TYPE_CHECKING:
    from .service import KnowledgeService, Who

# A sign-in the system refused: the source waits for a reconnect instead of retrying every schedule.
RECONNECT = {"AUTH_EXPIRED", "CONNECTION_REVOKED", "SIGN_IN_NOT_FOUND", "CONNECTION_NOT_LINKED", "SECRET_MISSING"}
# Items fetched at once from the system; the knowledge tools' rate window is the gateway's.
AT_ONCE = 4
# Pages one run reads before it stops partial and saves its place, so a listing that never ends cannot hold a run.
MAX_PAGES = 200
# A listing refused for its saved page: the system dropped it (a query locator expires), or the gateway's seal no
# longer opens it. The run starts the listing again from the watermark instead of failing every run on it.
STALE_CURSOR = {"INVALID_INPUT", "INVALID_ARGUMENTS"}
FULL_EVERY = timedelta(days=7)
# Syncs in a row an item must answer gone (404 or 410) before it is removed: one miss may be the site's hiccup.
GONE_TWICE = 2
# A tool that gives no watermark: the next run lists from the newest change seen, less this, so a record saved during
# a run is listed again rather than missed.
OVERLAP = timedelta(minutes=5)
TEAM_SIGN_IN = ("team",)


@dataclass(frozen=True)
class Answer:
    ok: bool
    output: Any = None
    code: str = ""
    message: str = ""


class ToolReader:
    """tools-service, as this service calls it: the sources a team can create, and one gateway call."""

    def __init__(self, tools: ServiceClient) -> None:
        self.tools = tools

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        return list(await self.tools.get("/v1/knowledge-sources", tenant=tenant_id, team=team_id) or [])

    async def source_hosts(
        self,
        tenant_id: str,
        team_id: str,
        cfg: dict[str, Any],
        *,
        credentials: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Each host the source's values would have its sync reach, decided by the account's egress rule as any new
        outside address is (tools-service `/v1/knowledge-sources/hosts`): asked as the person adding or changing the
        source (`credentials`), it lists the host where they may, asks the Security team, or is refused; asked as
        this service, it only reads whether each host passes now."""
        body: dict[str, Any] = {
            "plugin": cfg.get("plugin"),
            "source": cfg.get("source"),
            "values": cfg.get("values") or {},
        }
        kw: dict[str, Any] = {"tenant": tenant_id, "team": team_id}
        if credentials:
            # The person's own credentials decide; this service's token rides beside them.
            kw |= {"headers": credentials, "token_header": "X-Service-Authorization"}
        return list(await self.tools.post("/v1/knowledge-sources/hosts", json=body, **kw) or [])

    async def call(self, tenant_id: str, team_id: str, tool: str, args: dict[str, Any], *, act: str) -> Answer:
        body = {
            "tool": tool,
            "input": args,
            "key": new_id("kbcall"),
            # A sync acts on the source as it is: a live run (tools-service takes test or live).
            "runContext": {"act": act, "environment": "live"},
        }
        try:
            data = await self.tools.post("/v1/calls", json=body, tenant=tenant_id, team=team_id, timeout=60)
        except ServiceCallError as e:
            return Answer(False, code=str(e.code or "refused"), message=e.message)
        except ServiceUnreachable as e:
            return Answer(False, code="UPSTREAM_UNREACHABLE", message=str(e))
        answer = cast(dict[str, Any], data or {})
        if not answer.get("ok"):
            error = cast(dict[str, Any], cast(dict[str, Any], answer.get("output") or {}).get("error") or {})
            return Answer(False, code=str(error.get("code") or "TOOL_FAILED"), message=str(error.get("message") or ""))
        return Answer(True, answer.get("output"))


def refusal_of(found: dict[str, Any]) -> tuple[str, str] | None:
    """Why a source declared for the team cannot be made, as (code, message), or None when it can. Create and the
    Add source list both ask this, so a source is offered exactly when create accepts it."""
    if not found.get("needsConnection", True):
        return None
    if not found.get("connectionId"):
        return "connection_missing", f"{found['title']} needs the team's connection; sign in first."
    if found.get("signIn") not in TEAM_SIGN_IN:
        return (
            "sign_in_not_team",
            "This connection signs in each person. A knowledge source needs a team sign-in.",
        )
    return None


async def declared_source(reader: ToolReader | None, who: Who, plugin: str, name: str) -> dict[str, Any]:
    """The plugin's knowledge source as tools-service declares it for the team: refused unless the plugin is on,
    names the source, and its connection signs in with the team's account, since a sync has no person behind it."""
    if reader is None:
        raise ValidationFailed(
            "This service reads no tools, so a tool source cannot be made.", code="tools_unavailable"
        )
    team = str(who.team_id or "")
    found = next(
        (d for d in await reader.declared(who.tenant_id, team) if d["plugin"] == plugin and d["source"] == name), None
    )
    if found is None:
        raise ValidationFailed(
            f"{plugin or 'That plugin'} offers no source {name or '?'} to this team; turn it on first."
        )
    if (refusal := refusal_of(found)) is not None:
        raise ValidationFailed(refusal[1], code=refusal[0])
    return found


async def source_config(reader: ToolReader | None, who: Who, i: dict[str, Any]) -> dict[str, Any]:
    """A new tool source's config, from what tools-service declares for the team: refused unless the plugin is on,
    names the source, and its connection signs in with the team's account, since a sync has no person behind it."""
    wanted = cast(dict[str, Any], i.get("config") or {})
    plugin, name = str(wanted.get("plugin") or ""), str(wanted.get("source") or "")
    found = await declared_source(reader, who, plugin, name)
    cfg: dict[str, Any] = {
        "plugin": plugin,
        "source": name,
        # The plugin's name for this kind of source, which the source shows as its kind.
        "title": str(found.get("title") or ""),
        "listTool": found["listTool"],
        "getTool": found["getTool"],
        "changesTool": found.get("changesTool"),
        "scopesTool": found.get("scopesTool"),
        "previewTool": found.get("previewTool"),
        "listsWhole": bool(found.get("listsWhole")),
        "fetchAtOnce": int(found.get("fetchAtOnce") or AT_ONCE),
        # Its items are a website's pages, so it starts with a website's cleaning and splitting.
        "site": bool(found.get("site")),
        "getTakesTag": bool(found.get("getTakesTag")),
        "connectionId": found.get("connectionId"),
        "schedule": found.get("schedule") or {"kind": "manual"},
        # What this source is set up with (start addresses, sites, spaces), checked against what the plugin declares
        # and sent to each of its tools as `source`.
        "values": source_values(found, wanted.get("values")),
    }
    return {**cfg, "waitingHosts": await waiting_hosts(cast(ToolReader, reader), who, cfg)}


async def waiting_hosts(reader: ToolReader, who: Who, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """The source's hosts an admin has yet to approve, each with the Security task it waits on: a sync reaches a
    source's own site only once the account lists its host, under the same rule as every new outside address. A host
    the account refuses refuses the source."""
    answers = await reader.source_hosts(who.tenant_id, str(who.team_id or ""), cfg, credentials=who.credentials)
    refused = [h for h in answers if h.get("state") == "refused"]
    if refused:
        raise ValidationFailed(
            str(refused[0].get("reason") or f"{refused[0]['host']} is not an allowed address."),
            code="egress_host_refused",
        )
    return [{"host": str(h["host"]), "runKey": h.get("runKey")} for h in answers if h.get("state") == "waiting"]


INPUT_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def source_values(declared: dict[str, Any], given: Any) -> dict[str, Any]:
    """A source's own settings checked against the inputs its plugin declares: a required one present, each of its
    declared type, and nothing undeclared."""
    inputs = cast(dict[str, dict[str, Any]], declared.get("inputs") or {})
    values = cast(dict[str, Any], given) if isinstance(given, dict) else {}
    if unknown := sorted(set(values) - set(inputs)):
        raise ValidationFailed(f"{declared['title']} takes no {', '.join(unknown)}.", code="invalid_source_values")
    for name, field in inputs.items():
        if values.get(name) in (None, "", []):
            if field.get("required", True):
                raise ValidationFailed(f"{declared['title']} needs {name}.", code="invalid_source_values")
            continue
        expected = INPUT_TYPES.get(str(field.get("type") or "string"), str)
        if not isinstance(values[name], expected):
            raise ValidationFailed(
                f"{name} is a {field.get('type') or 'string'} for {declared['title']}.", code="invalid_source_values"
            )
    return values


def _content(item: dict[str, Any]) -> bytes:
    content = str(item.get("content") or "")
    return base64.b64decode(content) if item.get("encoding") == "base64" else content.encode()


def _filename(item: dict[str, Any]) -> str:
    """The name the parser reads the type from: the title with the extension its mime gives."""
    ext = {"text/html": ".html", "text/plain": ".txt", "text/markdown": ".md", "application/pdf": ".pdf"}
    title = str(item.get("title") or item.get("id") or "item")
    suffix = ext.get(str(item.get("mime") or ""), "")
    return title if title.endswith(suffix) else f"{title}{suffix}"


class Pacer:
    """One turn every `pace` seconds, shared by a sync's fetches whatever their concurrency."""

    def __init__(self, pace: float) -> None:
        self.pace = pace
        self.next = 0.0
        self.lock = asyncio.Lock()

    async def turn(self) -> None:
        if self.pace <= 0:
            return
        async with self.lock:
            now = time.monotonic()
            if self.next > now:
                await asyncio.sleep(self.next - now)
            self.next = max(now, self.next) + self.pace


def _listing(out: Any) -> list[dict[str, Any]] | None:
    """The page's items when the answer is a knowledge listing, else None."""
    if not isinstance(out, dict):
        return None
    items = cast(dict[str, Any], out).get("items")
    if not isinstance(items, list):
        return None
    rows = cast(list[Any], items)
    if not all(isinstance(r, dict) and {"id", "updated_at"} <= set(cast(dict[str, Any], r)) for r in rows):
        return None
    return [cast(dict[str, Any], r) for r in rows]


def _less_overlap(stamp: str) -> str:
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return stamp
    return f"{(when - OVERLAP).astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"


async def sync_tool_source(
    service: KnowledgeService,
    reader: ToolReader,
    who: Who,
    s: dict[str, Any],
    *,
    full: bool,
    trigger: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    cfg: dict[str, Any] = dict(s.get("config") or {})
    tenant, team, source_id = who.tenant_id, str(s["team_id"]), str(s["id"])
    act = f"kb-sync:{source_id}"
    if cfg.get("paused") == "needs_reconnect":
        healthy = any(
            d.get("connectionId") == cfg.get("connectionId") and d.get("connectionStatus") == "healthy"
            for d in await reader.declared(tenant, team)
        )
        if not healthy:
            raise Conflict(
                "The connection refused its sign-in. Reconnect it and run Test connection, then sync again.",
                code="needs_reconnect",
            )
        cfg.pop("paused", None)
    started = clock()
    last_full = cfg.get("lastFullAt")
    full = (
        full
        or bool(cfg.get("listsWhole"))
        or not cfg.get("watermark")
        or not last_full
        or started - datetime.fromisoformat(last_full) > FULL_EVERY
    )
    since = None if full else cfg.get("watermark")
    cursor = cfg.get("cursor") if trigger != "full" else None
    # The source's own settings go to every call; an incremental run lists only what changed when the plugin has a
    # changes tool and a cursor from the last run, else lists from the watermark.
    given: dict[str, Any] = {"source": cfg["values"]} if cfg.get("values") else {}
    by_changes = bool(not full and cfg.get("changesTool") and cfg.get("changesCursor"))
    list_tool = str(cfg["changesTool"] if by_changes else cfg["listTool"])
    if by_changes and not cursor:
        cursor = cfg["changesCursor"]
    removed_at_source: list[str] = []
    tombstones = cast(dict[str, Any], cfg.setdefault("tombstones", {}))
    gone_now: list[str] = []
    # Only a listing read from its first page sees every item, so only then is an unseen item removed. One longer than a
    # run's pages carries what it listed so far (`seenSoFar`) into the run that finishes it.
    from_start = cursor is None
    carried = set(cast(list[str], cfg.get("seenSoFar") or [])) if cursor else set[str]()
    whole = from_start or "seenSoFar" in cfg
    if from_start:
        cfg.pop("seenSoFar", None)
    known = {str(i["path"]): i for i in await service.store.items(tenant, source_ids=[source_id])}
    counts = {"listed": 0, "unchanged": 0, "upserted": 0, "deleted": 0, "failed": 0, "skipped": 0}
    errors: list[dict[str, Any]] = []
    log: list[str] = []
    status, stopped = "success", ""
    seen: set[str] = set()
    changed: list[dict[str, Any]] = []
    newest: str | None = None
    watermark: str | None = None

    async def save() -> None:
        await service.store.update_source(tenant, source_id, {"config": dict(cfg)})

    pages, restarted, resumes = 0, False, False
    # The seconds between two fetches of this source's items: the source's own rate, or the slower pace its listing
    # names (a site's robots.txt Crawl-delay). Each fetch is its own call, so the plugin cannot pace them itself.
    values = cast(dict[str, Any], cfg.get("values") or {})
    pace = 1.0 / float(values["rate"]) if isinstance(values.get("rate"), int | float) and values["rate"] > 0 else 0.0
    while True:
        if pages >= MAX_PAGES:
            # The items listed so far are fetched now; the next run lists on from the saved cursor.
            status, stopped = "partial", f"Listed {MAX_PAGES} pages; the next run continues the listing from here."
            resumes = True
            if whole:
                cfg["seenSoFar"] = sorted(carried | seen)
            break
        asked = {k: v for k, v in (("since", None if by_changes else since), ("cursor", cursor)) if v}
        page = await reader.call(tenant, team, list_tool, {**given, **asked}, act=act)
        pages += 1
        if not page.ok and cursor and not restarted and page.code in STALE_CURSOR:
            restarted, cursor = True, None
            cfg.pop("cursor", None)
            cfg.pop("seenSoFar", None)
            carried, whole = set[str](), True
            await save()
            continue
        if not page.ok:
            if page.code == "RATE_LIMITED":
                status, stopped = "partial", "Stopped at the system's rate limit; the next run continues from here."
            elif page.code in RECONNECT:
                status, stopped = "failed", "The connection refused its sign-in; reconnect it."
                cfg["paused"] = "needs_reconnect"
            elif page.code == "APP_OFF_FOR_TEAM":
                status, stopped = "skipped", "The plugin is off for this team."
            elif page.code == "PLUGIN_DISABLED":
                status, stopped = "skipped", "The plugin is not installed on this system."
            else:
                status, stopped = "failed", page.message or page.code
            errors.append({"phase": "list", "errorClass": page.code, "message": page.message or page.code})
            break
        rows = _listing(page.output)
        if rows is None:
            status, stopped = "failed", "The tool's answer is not a knowledge listing."
            errors.append({"phase": "list", "errorClass": "contract", "message": stopped})
            break
        out = cast(dict[str, Any], page.output)
        if isinstance(out.get("pace_s"), int | float):
            pace = max(pace, float(out["pace_s"]))
        for r in rows:
            item_id = str(r["id"])
            counts["listed"] += 1
            seen.add(item_id)
            newest = max(newest or "", str(r["updated_at"]))
            marker = str(r.get("marker") or r["updated_at"])
            if r.get("deleted"):
                removed_at_source.append(item_id)
                continue
            if item_id in tombstones:
                # Removed after answering gone twice: a link elsewhere does not bring it back until it is lifted.
                seen.discard(item_id)
                counts["skipped"] += 1
                continue
            if r.get("skipped"):
                # Listed but not to be taken in (refused by robots.txt, excluded by a rule): not seen, so an indexed
                # copy leaves search.
                seen.discard(item_id)
                counts["skipped"] += 1
                log.append(f"{r.get('title') or item_id}: {r['skipped']}")
                continue
            ex = known.get(item_id)
            if ex is not None and ex.get("marker") == marker and ex["status"] == "indexed":
                counts["unchanged"] += 1
            else:
                changed.append({**r, "marker": marker})
        if out.get("next_cursor") and out.get("next_cursor") == cursor:
            status, stopped = "partial", "The system named the same page again; the next run starts the listing again."
            errors.append({"phase": "list", "errorClass": "contract", "message": stopped})
            cfg.pop("cursor", None)
            await save()
            break
        cursor = out.get("next_cursor")
        # Saved after every page, so a run stopped by a limit or a restart resumes from here.
        cfg["cursor"] = cursor
        await save()
        if not cursor:
            watermark = str(out.get("watermark") or (_less_overlap(newest) if newest else since or ""))
            # The last page of a listing or of changes names where the next run's changes start.
            if out.get("cursor"):
                cfg["changesCursor"] = out["cursor"]
            break

    if not resumes:
        seen |= carried
        cfg.pop("seenSoFar", None)
    gone = [str(i["path"]) for i in known.values() if not i.get("parent_id")] if full and whole else []
    if status == "success" or resumes:
        lock = asyncio.Semaphore(int(cfg.get("fetchAtOnce") or AT_ONCE))
        paced = Pacer(pace)

        async def fetch(item_id: str) -> Answer:
            # The version tag held for the item lets the system answer `unchanged` without sending it again.
            held = known.get(item_id)
            tag = {"tag": held["tag"]} if cfg.get("getTakesTag") and held and held.get("tag") else {}
            async with lock:
                await paced.turn()
                return await reader.call(tenant, team, cfg["getTool"], {**given, "id": item_id, **tag}, act=act)

        # An item the listing already read (a crawl following links) is not fetched again.
        listed_whole = [r for r in changed if "content" in r]
        changed = [r for r in changed if "content" not in r]
        for r in listed_whole:
            await _put(service, who, s, known, r, marker=str(r["marker"]), parent=None, counts=counts, errors=errors)
        answers = await asyncio.gather(*(fetch(str(r["id"])) for r in changed))
        for r, got in zip(changed, answers, strict=True):
            if not got.ok and got.code == "NOT_FOUND" and (held := known.get(str(r["id"]))) is not None:
                # Gone at the source: removed on the second sync in a row that finds it gone, then tombstoned.
                count = int(held.get("gone_count") or 0) + 1
                await service.store.update_item(tenant, str(held["id"]), {"gone_count": count})
                if count >= GONE_TWICE:
                    gone_now.append(str(r["id"]))
                    tombstones[str(r["id"])] = {
                        "at": started.isoformat(),
                        "reason": got.message or "Gone at the source",
                    }
                else:
                    log.append(f"{held['title']}: answered gone once; removed if it answers so again")
                continue
            if not got.ok:
                counts["failed"] += 1
                errors.append(
                    {"itemTitle": r.get("title"), "phase": "get", "errorClass": got.code, "message": got.message}
                )
                if got.code == "RATE_LIMITED":
                    status = "partial"
                continue
            item = cast(dict[str, Any], got.output)
            if item.get("unchanged") is True:
                held = known.get(str(r["id"]))
                if held is not None:
                    await service.store.update_item(tenant, str(held["id"]), {"marker": str(r["marker"])})
                counts["unchanged"] += 1
                continue
            await _put(service, who, s, known, item, marker=str(r["marker"]), parent=None, counts=counts, errors=errors)
            for child in cast(list[dict[str, Any]], item.get("children") or []):
                kid_id = str(child["id"])
                seen.add(kid_id)
                marker = str(child.get("marker") or child.get("updated_at") or "")
                # An attachment is fetched only when its own marker moved, not each time its parent changes.
                ex = known.get(kid_id)
                if marker and ex is not None and ex.get("marker") == marker and ex["status"] == "indexed":
                    counts["unchanged"] += 1
                    continue
                kid = await fetch(kid_id)
                if kid.ok:
                    await _put(
                        service,
                        who,
                        s,
                        known,
                        cast(dict[str, Any], kid.output),
                        marker=marker,
                        parent=str(item["id"]),
                        counts=counts,
                        errors=errors,
                    )
                else:
                    counts["failed"] += 1
        # A base this source feeds may keep what its source removed: then it stays searchable and says so.
        keep = (await service.sync_rules(tenant, str(s["id"])))["removedAtSource"] == "keep"
        if gone_now:
            gone_ids = [str(known[p]["id"]) for p in gone_now]
            gone_files = [str(known[p]["file_id"]) for p in gone_now]
            if keep:
                await _flag_removed(service, tenant, gone_ids)
                for p in gone_now:
                    tombstones.pop(p, None)
            else:
                counts["deleted"] += await service.store.remove_items(tenant, gone_ids)
                await release_snapshots(service, who, s, gone_files)
            done = "kept and flagged" if keep else "removed and tombstoned"
            log += [f"{known[p]['title']}: gone at the source twice, {done}" for p in gone_now]
        if removed_at_source:
            # Items the system says it deleted (in a changes listing) leave search at once, with their attachments.
            out_ids = [str(known[p]["id"]) for p in removed_at_source if p in known]
            out_ids += [str(i["id"]) for i in known.values() if i.get("parent_id") in set(out_ids)]
            files_out = [str(i["file_id"]) for i in known.values() if str(i["id"]) in set(out_ids)]
            if keep:
                await _flag_removed(service, tenant, out_ids)
            else:
                counts["deleted"] += await service.store.remove_items(tenant, out_ids)
                await release_snapshots(service, who, s, files_out)
            done = "kept and flagged" if keep else "removed"
            log += [f"{known[p]['title']}: deleted at the source, {done}" for p in removed_at_source if p in known]
        if full and not resumes:
            dropped = [p for p in gone if p not in seen]
            removed_ids = [str(known[p]["id"]) for p in dropped]
            # Attachments go with their parent (parent_id holds the parent document's id).
            removed_ids += [str(i["id"]) for i in known.values() if i.get("parent_id") in set(removed_ids)]
            gone_files = [str(i["file_id"]) for i in known.values() if str(i["id"]) in set(removed_ids)]
            if keep:
                await _flag_removed(service, tenant, removed_ids)
            else:
                counts["deleted"] += await service.store.remove_items(tenant, removed_ids)
                await release_snapshots(service, who, s, gone_files)
            for p in dropped:
                log.append(
                    f"{known[p]['title']}: no longer listed by the system, {'kept and flagged' if keep else 'removed'}"
                )
        if status == "success":
            cfg["watermark"] = watermark
            cfg["cursor"] = None
            if full:
                cfg["lastFullAt"] = started.isoformat()
    if stopped:
        log.append(stopped)
    await save()
    run_status = "partial" if status == "partial" else "failed" if status == "failed" else "success"
    if status == "skipped":
        run_status = "skipped"
    indexed = counts["upserted"] > 0 or counts["unchanged"] > 0
    await service.settle_run(who, s, run_status, activate=indexed)
    if counts["upserted"] or counts["deleted"]:
        _, by_source = await service._joined(tenant)  # pyright: ignore[reportPrivateUsage]
        await service.store.refreshed(tenant, by_source.get(source_id, []))
    spent_on(counts, log)
    run = {
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
    s: dict[str, Any],
    known: dict[str, dict[str, Any]],
    item: dict[str, Any],
    *,
    marker: str,
    parent: str | None,
    counts: dict[str, int],
    errors: list[dict[str, Any]],
) -> None:
    """One fetched item, kept as a knowledge snapshot in files-service before it is read, so a rebuild never fetches
    it again and a citation opens the copy used. Unchanged when files-service's digest of its bytes is the stored one
    (its marker updated); else read through the shared reading step and indexed as a new document or the next version
    of the one stored under the system's id. The snapshot an older version used is let go."""
    data = _content(item)
    item_id = str(item["id"])
    ex = known.get(item_id)
    tenant, team, source_id = who.tenant_id, source_team(s), str(s["id"])
    name, mime = _filename(item), str(item.get("mime") or "text/plain")
    try:
        stored = await service.files.put(
            tenant, team, data, name=name, mime=mime, actor=f"kb-sync:{source_id}", purpose="knowledge_snapshot"
        )
        await service.files.use(tenant, team, stored.file_id, source_id=source_id, source_name=str(s["name"]))
    except (ValueError, FileNotScanned) as e:
        counts["failed"] += 1
        errors.append({"itemTitle": item.get("title"), "phase": "store", "errorClass": "snapshot", "message": str(e)})
        return
    if ex is not None and ex["digest"] == stored.digest and ex["status"] == "indexed":
        await service.store.update_item(tenant, str(ex["id"]), {"marker": marker})
        counts["unchanged"] += 1
        return
    extra: dict[str, Any] = {
        "marker": marker,
        "parent_id": None,
        "url": item.get("url"),
        "folder": str(item["folder"])[:400] if item.get("folder") else None,
        "fields": {str(k): str(v) for k, v in cast(dict[str, Any], item.get("metadata") or {}).items()} or None,
        "tag": str(item["marker"])[:200] if item.get("marker") else None,
        "gone_count": 0,
    }
    if parent is not None:
        parent_row = known.get(parent) or next(
            (i for i in await service.store.items(tenant, source_ids=[source_id]) if i["path"] == parent), None
        )
        extra["parent_id"] = parent_row["id"] if parent_row else None
    found = Stored(stored.file_id, name, stored.mime, stored.size, stored.digest, stored.deduplicated)
    allowed = cast(list[Any], item["allowed"]) if isinstance(item.get("allowed"), list) else None
    origin = Origin(item_id, str(item.get("title") or item_id), extra, allowed=[str(a) for a in allowed or []] or None)
    done = await service._read_file(who, s, ex, name=name, found=found, rebuild=False, origin=origin)  # pyright: ignore[reportPrivateUsage]
    known[item_id] = done
    if ex is not None and ex.get("file_id") and ex["file_id"] != stored.file_id:
        await release_snapshots(service, who, s, [str(ex["file_id"])])
    if done["status"] == "failed":
        counts["failed"] += 1
        errors.append(
            {
                "itemId": done["id"],
                "itemTitle": done["title"],
                "phase": "parse",
                "errorClass": done["error_class"],
                "message": done["error"],
            }
        )
    elif done["status"] == "reading":
        counts.setdefault("reading", 0)
        counts["reading"] += 1
    elif done.get("unchanged"):
        counts["unchanged"] += 1
    else:
        counts["upserted"] += 1


async def release_snapshots(service: KnowledgeService, who: Who, s: dict[str, Any], file_ids: list[str]) -> None:
    """Lets go of snapshots no item of the source uses any more; files-service keeps each for its retention days."""
    held = {str(i["file_id"]) for i in await service.store.items(who.tenant_id, source_ids=[str(s["id"])])}
    for file_id in dict.fromkeys(f for f in file_ids if f and f not in held):
        await service.files.release(who.tenant_id, source_team(s), file_id, source_id=str(s["id"]))


# What a kept item says once its source has removed it.
REMOVED_AT_SOURCE = "Removed at its source; kept because a knowledge base it feeds keeps removed items."


async def _flag_removed(service: KnowledgeService, tenant: str, item_ids: list[str]) -> None:
    """Items their source removed, kept searchable under a base's setting and marked so on the item."""
    for item_id in item_ids:
        await service.store.update_item(tenant, item_id, {"warning": REMOVED_AT_SOURCE})
