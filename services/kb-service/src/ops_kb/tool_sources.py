"""Knowledge read through a connection's tools (c-564; the planning repo docs/plans/ops-ai/
plugin-contents-and-knowledge.html).

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
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import Conflict, ValidationFailed
from ops_service_kit.ids import new_id

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

    async def call(self, tenant_id: str, team_id: str, tool: str, args: dict[str, Any], *, act: str) -> Answer:
        body = {
            "tool": tool,
            "input": args,
            "key": new_id("kbcall"),
            "runContext": {"act": act, "environment": "production"},
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


async def source_config(reader: ToolReader | None, who: Who, i: dict[str, Any]) -> dict[str, Any]:
    """A new tool source's config, from what tools-service declares for the team: refused unless the plugin is on,
    names the source, and its connection signs in with the team's account, since a sync has no person behind it."""
    if reader is None:
        raise ValidationFailed(
            "This service reads no tools, so a tool source cannot be made.", code="tools_unavailable"
        )
    wanted = cast(dict[str, Any], i.get("config") or {})
    plugin, name = str(wanted.get("plugin") or ""), str(wanted.get("source") or "")
    team = str(who.team_id or "")
    found = next(
        (d for d in await reader.declared(who.tenant_id, team) if d["plugin"] == plugin and d["source"] == name), None
    )
    if found is None:
        raise ValidationFailed(
            f"{plugin or 'That plugin'} offers no source {name or '?'} to this team; turn it on first."
        )
    if not found.get("connectionId"):
        raise ValidationFailed(
            f"{found['title']} needs the team's connection; sign in first.", code="connection_missing"
        )
    if found.get("signIn") not in TEAM_SIGN_IN:
        raise ValidationFailed(
            "This connection signs in each person. A knowledge source needs a team sign-in.", code="sign_in_not_team"
        )
    return {
        "plugin": plugin,
        "source": name,
        "listTool": found["listTool"],
        "getTool": found["getTool"],
        "connectionId": found["connectionId"],
        "schedule": found.get("schedule") or {"kind": "manual"},
    }


def _content(item: dict[str, Any]) -> bytes:
    content = str(item.get("content") or "")
    return base64.b64decode(content) if item.get("encoding") == "base64" else content.encode()


def _filename(item: dict[str, Any]) -> str:
    """The name the parser reads the type from: the title with the extension its mime gives."""
    ext = {"text/html": ".html", "text/plain": ".txt", "text/markdown": ".md", "application/pdf": ".pdf"}
    title = str(item.get("title") or item.get("id") or "item")
    suffix = ext.get(str(item.get("mime") or ""), "")
    return title if title.endswith(suffix) else f"{title}{suffix}"


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
    full = full or not cfg.get("watermark") or not last_full or started - datetime.fromisoformat(last_full) > FULL_EVERY
    since = None if full else cfg.get("watermark")
    cursor = cfg.get("cursor") if trigger != "full" else None
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

    pages, restarted = 0, False
    while True:
        if pages >= MAX_PAGES:
            status, stopped = "partial", f"Stopped after {MAX_PAGES} pages; the next run continues from here."
            break
        args = {k: v for k, v in (("since", since), ("cursor", cursor)) if v}
        page = await reader.call(tenant, team, cfg["listTool"], args, act=act)
        pages += 1
        if not page.ok and cursor and not restarted and page.code in STALE_CURSOR:
            restarted, cursor = True, None
            cfg.pop("cursor", None)
            await save()
            continue
        if not page.ok:
            if page.code == "RATE_LIMITED":
                status, stopped = "partial", "Stopped at the system's rate limit; the next run continues from here."
            elif page.code in RECONNECT:
                status, stopped = "failed", "The connection refused its sign-in; reconnect it."
                cfg["paused"] = "needs_reconnect"
            elif page.code == "PLUGIN_DISABLED":
                status, stopped = "skipped", "The plugin is off for this team."
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
        for r in rows:
            item_id = str(r["id"])
            counts["listed"] += 1
            seen.add(item_id)
            newest = max(newest or "", str(r["updated_at"]))
            marker = str(r.get("marker") or r["updated_at"])
            if r.get("deleted"):
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
            break

    gone = [str(i["path"]) for i in known.values() if not i.get("parent_id")] if full else []
    if status == "success":
        lock = asyncio.Semaphore(AT_ONCE)

        async def fetch(item_id: str) -> Answer:
            async with lock:
                return await reader.call(tenant, team, cfg["getTool"], {"id": item_id}, act=act)

        answers = await asyncio.gather(*(fetch(str(r["id"])) for r in changed))
        for r, got in zip(changed, answers, strict=True):
            if not got.ok:
                counts["failed"] += 1
                errors.append(
                    {"itemTitle": r.get("title"), "phase": "get", "errorClass": got.code, "message": got.message}
                )
                if got.code == "RATE_LIMITED":
                    status = "partial"
                continue
            item = cast(dict[str, Any], got.output)
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
        if full:
            dropped = [p for p in gone if p not in seen]
            removed_ids = [str(known[p]["id"]) for p in dropped]
            # Attachments go with their parent (parent_id holds the parent document's id).
            removed_ids += [str(i["id"]) for i in known.values() if i.get("parent_id") in set(removed_ids)]
            counts["deleted"] = await service.store.remove_items(tenant, removed_ids)
            for p in dropped:
                log.append(f"{known[p]['title']}: no longer listed by the system, removed")
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
    await service.store.mark_synced(tenant, source_id, run_status, activate=indexed)
    if counts["upserted"] or counts["deleted"]:
        _, by_source = await service._joined(tenant)  # pyright: ignore[reportPrivateUsage]
        await service.store.refreshed(tenant, by_source.get(source_id, []))
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
    """One fetched item: unchanged when its content's digest is the stored one (its marker updated), else indexed as
    a new document or the next version of the one stored under the system's id."""
    data = _content(item)
    digest = hashlib.sha256(data).hexdigest()
    item_id = str(item["id"])
    ex = known.get(item_id)
    if ex is not None and ex["digest"] == digest:
        await service.store.update_item(who.tenant_id, str(ex["id"]), {"marker": marker})
        counts["unchanged"] += 1
        return
    extra = {"marker": marker, "parent_id": None, "url": item.get("url")}
    if parent is not None:
        parent_row = known.get(parent) or next(
            (i for i in await service.store.items(who.tenant_id, source_ids=[str(s["id"])]) if i["path"] == parent),
            None,
        )
        extra["parent_id"] = parent_row["id"] if parent_row else None
    stored = await service._index(  # pyright: ignore[reportPrivateUsage]
        who,
        s,
        ex,
        file_id="",
        name=_filename(item),
        mime=str(item.get("mime") or "text/plain"),
        data=data,
        digest=digest,
        path=item_id,
        extra=extra,
        title_given=str(item.get("title") or item_id),
    )
    known[item_id] = stored
    if stored["status"] == "failed":
        counts["failed"] += 1
        errors.append(
            {
                "itemId": stored["id"],
                "itemTitle": stored["title"],
                "phase": "parse",
                "errorClass": stored["error_class"],
                "message": stored["error"],
            }
        )
    else:
        counts["upserted"] += 1
