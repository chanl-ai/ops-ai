"""Knowledge bases and sources as the console reads them (apps/console/src/lib/types/knowledge.ts): rows with joined
names, details with attached sources, and lists paged and filtered on the server.

Fields this slice does not run yet (access settings, precedence, automation, schedules) are served with the values a
new knowledge base or source starts with, so the console's pages render without a mock;
docs/services/kb-service/overview.md gives the designed surface and says which part is built.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ops_access import can, require_provisioner
from ops_documents_client import DocumentsRefused
from ops_identity import Principal, ServiceUnreachable
from ops_ingest import ParsedDocument, SplitResult, split
from ops_ingest.metadata import resolve_metadata
from ops_ingest.rules import ItemFacts, evaluate_rules
from ops_ingest.split import document_digest
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import options_page, options_window
from ops_service_kit.ids import new_id
from ops_service_kit.logging import get_logger
from ops_store.schedule import next_run

from .agents import AgentDirectory, Usage
from .embedding import Embedder, EmbedFailed, embed_pending
from .files import FileIntake, FileMissing, FileNotScanned, Stored
from .origin import Origin, source_team
from .readings import READING_PENDING, Readings, parsed_of, read_with
from .repeats import lines_of, repeated, without
from .retrieval import Found, Lane, Passage, Retriever, Search
from .search import lanes_for
from .source_settings import (
    WEB_SCHEDULE,
    InvalidSettings,
    SourceSettings,
    index_key,
    merged,
    rebuild_for,
    split_settings,
    stored,
    wire,
)
from .store import KnowledgeStore
from .store.vectors import PgVectorStore
from .tool_sources import ToolReader, source_config, sync_tool_source

# A new knowledge base's retrieval settings. searchMode, hybridWeight, chunkLimit and threshold decide every search of
# it (retrieval.py); the rest are the console's.
DEFAULT_RETRIEVAL: dict[str, Any] = {
    "searchMode": "hybrid",
    "hybridWeight": 0.6,
    "rerank": False,
    "reranker": "hosted",
    "chunkLimit": 8,
    "threshold": 0.5,
    "asOf": "",
    "rewrite": "off",
    "expandCount": 3,
    "rewriteInstructions": "",
    "scopeSourceIds": [],
    "answerShape": "answer_with_citations",
    "model": "bank-standard",
    "temperature": 0.1,
    "maxTokens": 800,
    "instructions": "Answer only from the provided context. If the context does not contain the answer, say so.",
    "citationStyle": "inline",
    "includeChunks": True,
    "noAnswerMessage": "I could not find that in the knowledge base.",
    "filters": {"match": "all", "conditions": []},
    "tagsInclude": [],
    "tagsExclude": [],
    "includeUntagged": True,
    "structuredTables": False,
}
PRESETS: dict[str, dict[str, Any]] = {
    "balanced": {"chunkLimit": 8, "threshold": 0.5, "answerShape": "answer_with_citations"},
    "precise": {"chunkLimit": 5, "threshold": 0.65, "answerShape": "answer_with_citations"},
    "raw": {"chunkLimit": 10, "threshold": 0.4, "answerShape": "chunks"},
}
SOURCE_TYPES_IN_PHASE = ("file", "tool")
SENSITIVITIES = ("internal", "confidential", "restricted")
MAX_PAGE_SIZE = 100
# How long a tool source's sync holds its lease; a sync that dies frees it when this passes.
LEASE = timedelta(minutes=15)


@dataclass(frozen=True)
class Who:
    tenant_id: str
    email: str
    team_id: str | None
    # The verified caller, which `ops_access.can` decides on. None for the seed, which acts as the system.
    caller: Principal | None = None

    def require_builder(
        self, team_id: str | None, action: str, step: str = "edit", protection: str | None = None
    ) -> None:
        """`can(knowledge, step)` in the team that owns the record, or the team the request acts in for a create or
        a record no team owns: 403 `role_required` naming the area and action otherwise. Knowledge is shared by its
        team, so the grid gives every builder and admin of the team `knowledge.edit` on all of it."""
        if self.caller is None:
            return
        can(self.caller, "knowledge", step, team=team_id or self.team_id, what=f"to {action}", protection=protection)

    def require_provisioner_for(self, body: dict[str, Any]) -> None:
        """Only the provisioning service sets `templateId` or `protection`; the seed, with no caller, may."""
        if self.caller is not None and (body.get("templateId") is not None or body.get("protection") is not None):
            require_provisioner(self.caller, "knowledge")


def _iso(v: datetime | None) -> str | None:
    return v.astimezone(UTC).isoformat() if v else None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def page_of(
    rows: list[dict[str, Any]], *, page: int, page_size: int, facets: dict[str, dict[str, int]]
) -> dict[str, Any]:
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    total = len(rows)
    total_pages = max(1, -(-total // page_size))
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    return {
        "data": rows[start : start + page_size],
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
            "hasNext": page < total_pages,
            "hasPrev": page > 1,
        },
        "facets": facets,
    }


def _facet(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[str(r[key])] = out.get(str(r[key]), 0) + 1
    return out


def _matches(search: str | None, *texts: str) -> bool:
    return not search or any(search.lower() in t.lower() for t in texts)


# The settings a source's patch may change, each validated and applied by its stage (source_settings.py).
SETTINGS_KEYS = ("parsing", "cleaning", "ingest", "rules", "metadataMapping", "schedule")
# The service event a source raises when it keeps failing, so a workflow can tell its owner.
FAILING_EVENT = "knowledge.source.failing"
FAILING_AFTER_RUNS = 2
FAILING_AFTER = timedelta(days=1)


# An item's status as the console names it: an item waiting for its file's reading is processing there.
SHOWN_STATUS = {"reading": "processing"}
# A file source's item when no documents-service is configured: kb-service reads no file itself.
NO_READER = ("parse", "Files are read by documents-service, which this installation does not run.")


def _no_text(error: str) -> tuple[str, str]:
    return "parse", f"no_text_layer: {error}"


def _used_by(using: dict[str, Usage] | None, kb_id: str) -> dict[str, Any]:
    """The agents of the caller's team citing the base, how many of other teams do, and whether that is known."""
    if using is None:
        return {"agentNames": [], "agentsElsewhere": 0, "agentsKnown": False}
    u = using.get(kb_id) or Usage()
    return {"agentNames": u.names, "agentsElsewhere": u.elsewhere, "agentsKnown": True}


def _item_counts(s: dict[str, Any]) -> dict[str, int]:
    """What the source's documents are, from their items; an uploaded file not yet synced has no item and is pending.
    A source row built in memory (just created) has no documents yet."""
    counts: dict[str, int] = s.get("item_counts") or {}
    synced = sum(counts.values())
    return {
        "itemsIndexed": counts.get("indexed", 0),
        "itemsFailed": counts.get("failed", 0),
        "itemsPending": counts.get("pending", 0) + counts.get("reading", 0) + max(len(s["file_ids"]) - synced, 0),
    }


logger = get_logger(__name__)


class KnowledgeService:
    def __init__(
        self,
        store: KnowledgeStore,
        files: FileIntake,
        retriever: Retriever,
        agents: AgentDirectory,
        tools: ToolReader | None = None,
        *,
        readings: Readings | None = None,
        ocr: str = "auto",
        embedder: Embedder | None = None,
        vectors: PgVectorStore | None = None,
    ) -> None:
        """`tools` reads "tool" sources through tools-service's gateway; without it none can be made. `readings` gives
        each file's reading from documents-service, read with OCR mode `ocr` (settings.kb_ocr); without it a file
        source's items fail with the reason."""
        self.store = store
        self.files = files
        self.retriever = retriever
        self.agents = agents
        self.readings = readings
        self.ocr = ocr
        self.tools = tools
        # The environment's embedding model and the vector store: units a sync settled are embedded at once.
        self.embedder = embedder
        self.vectors = vectors
        # Rebuilds running in this process, so stopping the service ends them and their runs say why.
        self.rebuilds: set[asyncio.Task[None]] = set()

    # ── Serialising ──────────────────────────────────────────────────────

    def settings_of(self, s: dict[str, Any]) -> SourceSettings:
        """The source's saved settings over its kind's defaults; the environment's OCR mode is the default's. A plugin
        source whose items are a website's pages starts with a website's defaults."""
        return stored(kind_of(s), s.get("settings"), ocr=self.ocr)

    def schedule_of(self, s: dict[str, Any]) -> dict[str, Any]:
        """When the source syncs on its own: its saved schedule, else its plugin's for its kind of source, else a
        website's daily check, else manual."""
        saved = self.settings_of(s).schedule
        if saved is not None:
            return saved
        cfg = dict(s.get("config") or {})
        if kind_of(s) == "web":
            return WEB_SCHEDULE
        return cast(dict[str, Any], cfg.get("schedule") or {"kind": "manual"})

    def key_of(self, s: dict[str, Any]) -> str:
        """The digest an item built now under the source's settings records (`indexed_with`)."""
        return index_key(self.settings_of(s), repeats_of(s))

    def _source(self, s: dict[str, Any], used_by: list[str]) -> dict[str, Any]:
        tool = s["type"] == "tool"
        cfg: dict[str, Any] = dict(s.get("config") or {})
        applied = wire(self.settings_of(s))
        return {
            "id": s["id"],
            "type": s["type"],
            "name": s["name"],
            "scopeSummary": f"{cfg.get('plugin')} {cfg.get('source')}"
            if tool
            else f"{len(s['file_ids'])} uploaded files",
            "config": (
                {k: cfg.get(k) for k in ("plugin", "source", "listTool", "getTool", "connectionId", "paused")}
                if tool
                else {"fileIds": s["file_ids"]}
            ),
            # Every stage's settings as a sync applies them.
            "parsing": applied["parsing"],
            "cleaning": applied["cleaning"],
            "ingest": applied["ingest"],
            "rules": applied["rules"],
            "metadataMapping": applied["metadataMapping"],
            "tags": s["tags"],
            "titleFrom": "heading",
            "permissions": {"mode": "workspace"},
            "schedule": (schedule := self.schedule_of(s)),
            **(
                {"nextSyncAt": _iso(n)}
                if s["status"] == "active" and (n := next_run(schedule, s.get("last_sync_at"), datetime.now(UTC)))
                else {}
            ),
            "health": health_of(s),
            "deletedAtSource": "remove",
            "staleAfterDays": 365,
            "notifyOnFailure": True,
            "sensitivity": s["sensitivity"],
            "collection": s["collection"],
            "owner": s["owner"],
            "status": s["status"],
            **_item_counts(s),
            **({"lastSyncAt": _iso(s["last_sync_at"])} if s["last_sync_at"] else {}),
            **({"lastRunStatus": s["last_run_status"]} if s["last_run_status"] else {}),
            "usedByKbIds": used_by,
            "createdAt": _iso(s["created_at"]),
        }

    async def _counts(self, tenant: str) -> dict[str, dict[str, Any]]:
        """Each source's documents by status and its indexed chunks, from its items, and when it last synced."""
        rows = await self.store.sources(tenant)
        return {str(x["id"]): {**x["item_counts"], "synced": x.get("last_sync_at")} for x in rows}

    def _base(self, b: dict[str, Any], source_ids: list[str], counts: dict[str, dict[str, Any]]) -> dict[str, Any]:
        mine = [counts.get(sid, {}) for sid in source_ids]
        # When the base was last read: its newest source sync, the same time each source row shows. Content changing
        # (lastRefreshedAt) is a separate fact, and a sync that changes nothing does not move it.
        synced = max((c["synced"] for c in mine if c.get("synced")), default=None)
        documents = sum(c.get("indexed", 0) for c in mine)
        failures = sum(c.get("failed", 0) for c in mine)
        if b["last_refreshed_at"] is None:
            health, reasons = "never", ["Never indexed"]
        elif failures:
            health, reasons = "degraded", [f"{failures} document{'s' if failures != 1 else ''} failed to index"]
        else:
            health, reasons = "healthy", []
        return {
            "id": b["id"],
            "name": b["name"],
            "slug": b["slug"],
            "templateId": b.get("template_id"),
            "protection": b.get("protection"),
            "description": b["description"],
            "color": b["color"],
            "owner": b["owner"],
            "sources": [
                {"sourceId": s, "itemsContributed": counts.get(s, {}).get("indexed", 0), "rules": []}
                for s in source_ids
            ],
            "collections": b["collections"],
            "precedence": [],
            "metadataProfile": {"required": []},
            "retrieval": b["retrieval"],
            "access": {
                "members": {"mode": "all", "principals": []},
                "anyApiKey": False,
                "mcp": {"enabled": False, "toolName": f"search_{b['slug']}"},
                "publicLink": {
                    "enabled": False,
                    "slug": b["slug"].replace("_", "-"),
                    "answerStyle": "chat",
                    "rateLimit": 300,
                    "showSourceLinks": True,
                },
                "documentPermissions": "workspace",
            },
            "automation": "suggest",
            # Queries are not logged yet, so their counts are 0 and the console does not show them; staleness is not
            # tracked (every document is fresh).
            "stats": {
                "documents": documents,
                "chunks": sum(c.get("chunks", 0) for c in mine),
                "failures": failures,
                "stale": 0,
                "queries7d": 0,
                "queriesChange7d": 0,
                "noAnswerRate": 0,
                "medianLatencyMs": 0,
            },
            "health": health,
            "healthReasons": reasons,
            **({"lastRefreshedAt": _iso(b["last_refreshed_at"])} if b["last_refreshed_at"] else {}),
            **({"lastSyncAt": _iso(synced)} if synced else {}),
            "jobs": [],
            "createdAt": _iso(b["created_at"]),
        }

    async def _joined(self, tenant: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """Source ids per knowledge base, and knowledge base ids per source."""
        by_kb: dict[str, list[str]] = {}
        by_source: dict[str, list[str]] = {}
        for kb_id, source_id in sorted(await self.store.links(tenant)):
            by_kb.setdefault(kb_id, []).append(source_id)
            by_source.setdefault(source_id, []).append(kb_id)
        return by_kb, by_source

    # ── Knowledge bases ──────────────────────────────────────────────────

    async def base_options(
        self, who: Who, *, search: str, cursor: str | None, limit: int, ids: list[str] | None
    ) -> dict[str, Any]:
        """The agent page's knowledge picker: each base as an option storing its id, labelled by name, with its
        owner as the hint. `ids` resolves stored values to labels; one not found is left out."""
        offset, window = options_window(None if ids else cursor, limit)
        rows = await self.store.base_options(
            who.tenant_id, who.team_id, search=search, offset=offset, limit=window, ids=ids
        )
        options = [{"id": r["id"], "label": r["name"], "hint": r["owner"] or None, "disabled": None} for r in rows]
        return options_page(options, offset, limit)

    async def list_bases(
        self, who: Who, *, page: int, page_size: int, search: str | None, template_id: str | None = None
    ) -> dict[str, Any]:
        bases = [
            b
            for b in await self.store.bases(who.tenant_id)
            if template_id is None or b.get("template_id") == template_id
        ]
        sources = {s["id"]: s for s in await self.store.sources(who.tenant_id)}
        by_kb, _ = await self._joined(who.tenant_id)
        using = await self.agents.usage(who.tenant_id, who.team_id)
        rows = [
            {
                **self._base(b, by_kb.get(b["id"], []), await self._counts(who.tenant_id)),
                "sourceNames": [sources[s]["name"] for s in by_kb.get(b["id"], []) if s in sources],
                **_used_by(using, b["id"]),
            }
            for b in sorted(bases, key=lambda b: b["created_at"], reverse=True)
            if _matches(search, b["name"], b["description"], b["owner"])
        ]
        return page_of(rows, page=page, page_size=page_size, facets={"health": _facet(rows, "health")})

    async def get_base(self, who: Who, kb_id: str) -> dict[str, Any]:
        b = await self.store.base(who.tenant_id, kb_id)
        if b is None:
            raise NotFound("No knowledge base with that id.")
        by_kb, by_source = await self._joined(who.tenant_id)
        attached = await self.store.sources(who.tenant_id, by_kb.get(kb_id, []))
        using = await self.agents.usage(who.tenant_id, who.team_id)
        return {
            **self._base(b, by_kb.get(kb_id, []), await self._counts(who.tenant_id)),
            "sourceNames": [s["name"] for s in attached],
            **_used_by(using, kb_id),
            "attached": [
                {
                    "sourceId": s["id"],
                    "itemsContributed": s["item_counts"].get("indexed", 0),
                    "rules": [],
                    "source": self._source(s, by_source.get(s["id"], [])),
                }
                for s in attached
            ],
            "metadataKeys": [],
            "suggestedQuestions": [],
            "heldCount": 0,
            **self._rights(who, b["team_id"], b["name"], b.get("protection")),
        }

    async def create_base(self, who: Who, i: dict[str, Any]) -> dict[str, Any]:
        who.require_builder(who.team_id, "create a knowledge base", "create")
        name = str(i.get("name") or "").strip()
        if not name:
            raise ValidationFailed("Give the knowledge base a name.")
        owner = str(i.get("owner") or "").strip()
        if not owner:
            raise ValidationFailed(
                "Name the knowledge base's owner: the person who answers for what it serves.",
                code="collection_without_owner",
            )
        existing = await self.store.taken(who.tenant_id, name=name, kb_id=i.get("id") or None)
        if any(b["name"].lower() == name.lower() for b in existing):
            raise Conflict("A knowledge base with this name already exists.")
        if i.get("id") and any(b["id"] == i["id"] for b in existing):
            raise Conflict(f"A knowledge base with id {i['id']} already exists.")
        who.require_provisioner_for(i)
        source_ids = list(dict.fromkeys(i.get("sourceIds") or []))
        await self._known_sources(who, source_ids)
        preset = PRESETS.get(str(i.get("preset") or "balanced"), PRESETS["balanced"])
        row: dict[str, Any] = {
            "tenant_id": who.tenant_id,
            "id": i.get("id") or new_id("kb"),
            "team_id": who.team_id,
            "name": name,
            "slug": _slug(name),
            "description": str(i.get("description") or ""),
            "color": str(i.get("color") or "blue"),
            "owner": owner,
            "collections": list(i.get("collections") or []),
            "retrieval": {**DEFAULT_RETRIEVAL, **preset},
            "created_by": who.email,
            "created_at": datetime.now(UTC),
            "last_refreshed_at": None,
            "template_id": i.get("templateId"),
            "protection": i.get("protection"),
        }
        await self.store.create_base(row, source_ids)
        return self._base(row, source_ids, await self._counts(who.tenant_id))

    @staticmethod
    def _may_change(
        who: Who, team_id: str | None, what: str, step: str = "edit", protection: str | None = None
    ) -> None:
        """Who changes knowledge (bases, sources, items, links): any builder or admin of the team that owns it.
        Knowledge is shared by the team; `owner` names who answers for the content, not
        who may change it. Viewers and reviewers get 403; the decision is `can()`'s. A system record is
        changed by the provisioning service only."""
        who.require_builder(
            team_id, f"{'delete' if step == 'delete' else 'change'} {what}", step, protection=protection
        )

    def _rights(self, who: Who, team_id: str | None, what: str, protection: str | None) -> dict[str, bool]:
        """`canEdit`, `canDelete` and `canPublish` for a detail response, from the check the write routes run,
        so the console never disagrees with them. Knowledge is changed in place, never published."""
        out: dict[str, bool] = {"canPublish": False}
        for step, flag in (("edit", "canEdit"), ("delete", "canDelete")):
            try:
                self._may_change(who, team_id, what, step, protection=protection)
                out[flag] = True
            except Forbidden:
                out[flag] = False
        return out

    async def _changeable(self, who: Who, kb_id: str, step: str = "edit") -> dict[str, Any]:
        """The knowledge base, when the caller may change it (`_may_change`)."""
        b = await self.store.base(who.tenant_id, kb_id)
        if b is None:
            raise NotFound("No knowledge base with that id.")
        self._may_change(who, b["team_id"], b["name"], step, protection=b.get("protection"))
        return b

    async def update_base(self, who: Who, kb_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        b = await self._changeable(who, kb_id)
        who.require_provisioner_for(patch)
        values: dict[str, Any] = {
            col: patch[key]
            for col, key in (("template_id", "templateId"), ("protection", "protection"))
            if patch.get(key)
        }
        if patch.get("name") is not None:
            name = str(patch["name"]).strip()
            if not name:
                raise ValidationFailed("Give the knowledge base a name.")
            taken = any(x["id"] != kb_id for x in await self.store.taken(who.tenant_id, name=name))
            if taken:
                raise Conflict("A knowledge base with this name already exists.")
            values |= {"name": name, "slug": _slug(name)}
        if patch.get("owner") is not None:
            if not str(patch["owner"]).strip():
                raise ValidationFailed("A knowledge base always has an owner.", code="collection_without_owner")
            values["owner"] = str(patch["owner"]).strip()
        for key in ("description", "color", "collections"):
            if patch.get(key) is not None:
                values[key] = patch[key]
        if patch.get("retrieval") is not None:
            values["retrieval"] = {**b["retrieval"], **patch["retrieval"]}
        if values:
            entry = audit_entry(who, "knowledge.base.settings", "knowledge_base", kb_id, b["name"], b, values)
            await self.store.update_base(who.tenant_id, kb_id, values, audit=entry)
        by_kb, _ = await self._joined(who.tenant_id)
        return self._base({**b, **values}, by_kb.get(kb_id, []), await self._counts(who.tenant_id))

    async def attach(self, who: Who, kb_id: str, source_ids: list[str]) -> dict[str, Any]:
        b = await self._changeable(who, kb_id)
        await self._known_sources(who, source_ids)
        await self.store.attach(who.tenant_id, kb_id, source_ids)
        by_kb, _ = await self._joined(who.tenant_id)
        return self._base(b, by_kb.get(kb_id, []), await self._counts(who.tenant_id))

    async def remove_base(self, who: Who, kb_id: str) -> None:
        await self._changeable(who, kb_id, "delete")
        if not await self.store.remove_base(who.tenant_id, kb_id, by=who.email):
            raise NotFound("No knowledge base with that id.")

    async def _known_sources(self, who: Who, source_ids: list[str]) -> None:
        found = {s["id"] for s in await self.store.sources(who.tenant_id, source_ids)}
        if missing := [s for s in source_ids if s not in found]:
            raise NotFound(f"No source with id {missing[0]}.")

    # ── Sources ──────────────────────────────────────────────────────────

    async def list_sources(self, who: Who, *, page: int, page_size: int, search: str | None) -> dict[str, Any]:
        sources = await self.store.sources(who.tenant_id)
        bases = {b["id"]: b for b in await self.store.bases(who.tenant_id)}
        _, by_source = await self._joined(who.tenant_id)
        running = await self.store.running_sources(who.tenant_id)
        rows = [
            {
                **self._source(s, by_source.get(s["id"], [])),
                "usedBy": [{"id": k, "name": bases[k]["name"]} for k in by_source.get(s["id"], []) if k in bases],
                "running": s["id"] in running,
            }
            for s in sorted(sources, key=lambda s: s["created_at"], reverse=True)
            if _matches(search, s["name"], s["owner"], s["collection"])
        ]
        facets = {"type": _facet(rows, "type"), "status": _facet(rows, "status")}
        return page_of(rows, page=page, page_size=page_size, facets=facets)

    async def plugin_sources(self, who: Who, plugin: str) -> list[dict[str, Any]]:
        """The sources the caller's team made from one plugin's knowledge sources, each with the bases it feeds. Read
        by the team the call names, a service's included, so an app's resource list shows only that team's."""
        if not who.team_id:
            raise ValidationFailed(
                "Plugin sources are listed for one team; this call names none.", code="team_required"
            )
        _, by_source = await self._joined(who.tenant_id)
        return [
            {
                "id": s["id"],
                "name": s["name"],
                "source": str(cfg.get("source") or ""),
                "kbIds": by_source.get(s["id"], []),
            }
            for s in await self.store.sources(who.tenant_id)
            if s["type"] == "tool"
            and s.get("team_id") == who.team_id
            and (cfg := dict(s.get("config") or {})).get("plugin") == plugin
        ]

    async def get_source(self, who: Who, source_id: str) -> dict[str, Any]:
        found = await self.store.sources(who.tenant_id, [source_id])
        if not found:
            raise NotFound("No source with that id.")
        s = found[0]
        _, by_source = await self._joined(who.tenant_id)
        readers = [b for b in await self.store.bases(who.tenant_id) if b["id"] in by_source.get(source_id, [])]
        recent = [_run(r) for r in (await self.store.runs(who.tenant_id, source_id=source_id))[:5]]
        items = await self.store.items(who.tenant_id, source_ids=[source_id])
        return {
            **self._source(s, by_source.get(source_id, [])),
            "readers": [
                {
                    "id": b["id"],
                    "name": b["name"],
                    "slug": b["slug"],
                    "color": b["color"],
                    "health": self._base(b, [], await self._counts(who.tenant_id))["health"],
                }
                for b in readers
            ],
            "recentRuns": recent,
            "running": next((r for r in recent if r["status"] == "running"), None),
            **self._rights(who, s["team_id"], s["name"], s.get("protection")),
            # The Last sync tile's "Took ..." hint; absent until a first run.
            **({"lastRunDurationSec": recent[0]["durationSec"]} if recent else {}),
            "errorGroups": [],
            "itemCount": sum(s["item_counts"].values()),
            "reindexNeeded": any(self.built_under_other_settings(s, i) for i in items),
            "requiredMetadata": [],
            "governance": {
                "excluded": 0,
                "held": 0,
                "duplicates": sum(1 for i in items if i.get("duplicate_of") or i["status"] == "skipped"),
                "superseded": 0,
            },
            "aiStepsWaiting": [],
        }

    async def create_source(self, who: Who, i: dict[str, Any]) -> dict[str, Any]:
        who.require_builder(who.team_id, "create a source", "create")
        kind = str(i.get("type") or "")
        if kind not in SOURCE_TYPES_IN_PHASE:
            raise ValidationFailed(
                f"{kind or 'That'} sources are not built yet; upload files instead.", code="type_unsupported_in_phase"
            )
        name = str(i.get("name") or "").strip()
        if not name:
            raise ValidationFailed("Give the source a name.")
        sensitivity = str(i.get("sensitivity") or "internal")
        if sensitivity not in SENSITIVITIES:
            raise ValidationFailed(f"Sensitivity is one of {', '.join(SENSITIVITIES)}.")
        kb_ids = list(dict.fromkeys(i.get("kbIds") or []))
        # Linking a source changes what each base cites, so it takes the right to change every base named.
        for kb_id in kb_ids:
            await self._changeable(who, kb_id)
        row: dict[str, Any] = {
            "tenant_id": who.tenant_id,
            "id": new_id("src"),
            "team_id": who.team_id,
            "type": kind,
            "name": name,
            "collection": str(i.get("collection") or ""),
            "owner": str(i.get("owner") or who.email),
            "sensitivity": sensitivity,
            "status": "draft" if i.get("status") == "draft" else "active",
            "tags": list(i.get("tags") or []),
            "file_ids": [],
            "created_by": who.email,
            "created_at": datetime.now(UTC),
            "last_sync_at": None,
            "last_run_status": None,
        }
        if kind == "tool":
            # Read through a connection's tools: what tools-service declares for the team, checked now.
            row["config"] = await source_config(self.tools, who, i)
        given = {k: i[k] for k in SETTINGS_KEYS if i.get(k) is not None}
        row["settings"] = wire(self._merged(self.settings_of(row), given)) if given else None
        # Files named at creation are checked and referenced like any added later, before the source exists.
        names = [await self._use_file(who, row, f) for f in dict.fromkeys(i.get("fileIds") or [])]
        row["file_ids"] = [f for f, _ in names]
        row["file_names"] = dict(names)
        await self.store.create_source(row, kb_ids)
        return self._source(row, kb_ids)

    async def source_kinds(self, who: Who) -> list[dict[str, Any]]:
        """Files, then each knowledge source the team's apps offer (none when this service reads no tools)."""
        out: list[dict[str, Any]] = [{"type": "file", "group": "built_in", "title": "Files"}]
        if self.tools is None or not who.team_id:
            return out
        for d in await self.tools.declared(who.tenant_id, str(who.team_id)):
            needs = bool(d.get("needsConnection", True))
            out.append(
                {
                    "type": "tool",
                    "group": "apps",
                    "title": str(d["title"]),
                    "plugin": d["plugin"],
                    "source": d["source"],
                    "site": bool(d.get("site")),
                    "needsConnection": needs,
                    "connected": not needs or (bool(d.get("connectionId")) and d.get("connectionStatus") == "healthy"),
                    "previews": bool(d.get("previewTool")),
                    "pickers": bool(d.get("scopesTool")),
                    "inputs": d.get("inputs") or {},
                }
            )
        return out

    async def preview_source(self, who: Who, i: dict[str, Any]) -> dict[str, Any]:
        """A plugin source's preview before it is made: its settings checked as a create checks them, then the
        plugin's preview tool asked what they would take in."""
        who.require_builder(who.team_id, "preview a source", "create")
        cfg = await source_config(self.tools, who, i)
        if not cfg.get("previewTool") or self.tools is None:
            raise ValidationFailed("This kind of source has no preview.", code="preview_unavailable")
        given = {"source": cfg["values"]} if cfg.get("values") else {}
        answer = await self.tools.call(
            who.tenant_id, str(who.team_id), str(cfg["previewTool"]), given, act="kb-preview"
        )
        if not answer.ok:
            # The plugin or the site failed, not this request: said as the store being unavailable, with its reason.
            raise ServiceUnavailable(
                f"The preview could not run: {answer.message or answer.code}", code="preview_failed"
            )
        out = cast(dict[str, Any], answer.output or {})
        rows = cast(list[dict[str, Any]], out.get("pages") or [])
        fetching = [bool(p.get("will_fetch")) for p in rows]
        pages: list[dict[str, Any]] = [
            {"id": str(p.get("id")), "outcome": str(p.get("outcome") or ""), "willFetch": f}
            for p, f in zip(rows, fetching, strict=True)
        ]
        return {
            "found": int(out.get("found") or len(pages)),
            "willFetch": int(out.get("will_fetch") or sum(fetching)),
            "pages": pages,
            "capped": bool(out.get("capped")),
        }

    async def remove_source(self, who: Who, source_id: str) -> None:
        await self._changeable_source(who, source_id, "delete")
        if not await self.store.remove_source(who.tenant_id, source_id):
            raise NotFound("No source with that id.")

    # ── Files and sync ───────────────────────────────────────────────────

    async def _source_row(self, who: Who, source_id: str) -> dict[str, Any]:
        found = await self.store.sources(who.tenant_id, [source_id])
        if not found:
            raise NotFound("No source with that id.")
        return found[0]

    async def _changeable_source(self, who: Who, source_id: str, step: str = "edit") -> dict[str, Any]:
        """The source, when the caller may change what it holds (`_may_change`)."""
        s = await self._source_row(who, source_id)
        self._may_change(who, s["team_id"], s["name"], step)
        return s

    async def upload(self, who: Who, source_id: str, data: bytes, *, name: str, mime: str) -> dict[str, Any]:
        """Stores bytes kb-service writes itself (a page, the demo seed) and adds them to the source under `name`.
        People add files through Files and `add_files`."""
        s = await self._changeable_source(who, source_id)
        if not data:
            raise ValidationFailed("The file is empty.")
        if not name.strip():
            raise ValidationFailed("The file needs a name.")
        try:
            stored = await self.files.put(who.tenant_id, source_team(s), data, name=name, mime=mime, actor=who.email)
        except ValueError as e:
            raise ValidationFailed(str(e), code="file_not_ready") from e
        await self.store.add_file(who.tenant_id, source_id, stored.file_id, name)
        return {
            "fileId": stored.file_id,
            # The name it was uploaded under, which the source indexes it by; the stored blob may carry an earlier one.
            "name": name,
            "mime": stored.mime,
            "size": stored.size,
            "digest": stored.digest,
            "deduplicated": stored.deduplicated,
        }

    async def _use_file(self, who: Who, s: dict[str, Any], file_id: str) -> tuple[str, str]:
        try:
            name = await self.files.use(
                who.tenant_id, source_team(s), file_id, source_id=s["id"], source_name=s["name"]
            )
        except FileMissing as e:
            raise UnknownFile(f"No file {file_id} in this team's Files.") from e
        except FileNotScanned as e:
            raise Conflict(
                f"{file_id} is not scanned clean yet, so it cannot be added; try again once Files shows it clean.",
                code="file_not_ready",
            ) from e
        return file_id, name

    async def add_files(self, who: Who, source_id: str, file_ids: list[str]) -> list[dict[str, str]]:
        """Adds files already in Files to the source by id. Every id is checked before any is added, so a refused id
        leaves the source as it was, and the references Files took for the ids before it are released; an id the
        source holds is added once."""
        s = await self._changeable_source(who, source_id)
        held = set(cast(list[str], s.get("file_ids") or []))
        used: list[tuple[str, str]] = []
        try:
            for f in dict.fromkeys(file_ids):
                used.append(await self._use_file(who, s, f))
        except Exception:
            for file_id, _ in used:
                if file_id not in held:
                    await self.files.release(who.tenant_id, source_team(s), file_id, source_id=source_id)
            raise
        for file_id, name in used:
            await self.store.add_file(who.tenant_id, source_id, file_id, name)
        return [{"fileId": f, "name": n} for f, n in used]

    async def sync(self, who: Who, source_id: str, *, full: bool = False, retry: bool = False) -> dict[str, Any]:
        s = await self._changeable_source(who, source_id)
        if s["type"] == "tool":
            return await self.sync_tool(who, s, full=full, trigger="full" if full else "manual")
        return await self._held_sync(who, s, full=full, retry=retry)

    async def scheduled_sync(self, who: Who, s: dict[str, Any]) -> dict[str, Any]:
        """A sync the schedule starts, of either kind, recorded with trigger `schedule`."""
        if s["type"] == "tool":
            return await self.sync_tool(who, s, full=False, trigger="schedule")
        return await self._held_sync(who, s, full=False, retry=False, trigger="schedule")

    async def _held_sync(
        self, who: Who, s: dict[str, Any], *, full: bool, retry: bool, trigger: str | None = None
    ) -> dict[str, Any]:
        """A file source's sync under its lease, so a rebuild, the schedule and a manual sync never run it at once."""
        source_id = str(s["id"])
        if not await self.store.claim(who.tenant_id, source_id, until=datetime.now(UTC) + LEASE):
            raise Conflict(f"{s['name']} is syncing or rebuilding now; wait for that run to end.", code="sync_running")
        try:
            return await self._sync(who, s, full=full, retry=retry, trigger=trigger)
        finally:
            await self.store.release(who.tenant_id, source_id)

    async def sync_tool(self, who: Who, s: dict[str, Any], *, full: bool, trigger: str) -> dict[str, Any]:
        """A tool source's sync under its lease, so a manual sync and the schedule never run it at once."""
        if self.tools is None:
            raise Conflict("This service reads no tools, so the source cannot sync.", code="tools_unavailable")
        if s["status"] == "paused":
            raise Conflict(f"{s['name']} is paused; resume it to sync.", code="source_paused")
        if not await self.store.claim(who.tenant_id, str(s["id"]), until=datetime.now(UTC) + LEASE):
            raise Conflict(f"{s['name']} is syncing now; wait for that run to end.", code="sync_running")
        try:
            run = _run(await sync_tool_source(self, self.tools, who, s, full=full, trigger=trigger))
        finally:
            await self.store.release(who.tenant_id, str(s["id"]))
        await self.settle_repeats(who, str(s["id"]))
        return run

    async def settle_repeats(self, who: Who, source_id: str) -> None:
        """Counts the lines repeated across a website source's pages after a sync; when the set changed, the pages
        built under the old set are rebuilt in the background from their snapshots, with nothing fetched."""
        s = await self._source_row(who, source_id)
        if not self.settings_of(s).cleaning.site_repeats:
            return
        items = [i for i in await self.store.items(who.tenant_id, source_ids=[source_id]) if i["status"] == "indexed"]
        found = repeated(i.get("lines") for i in items)
        cfg = dict(s.get("config") or {})
        if found == list(cfg.get("repeats") or []):
            return
        cfg["repeats"] = found
        await self.store.update_source(who.tenant_id, source_id, {"config": cfg})
        await self.start_rebuild(who, {**s, "config": cfg})

    async def settle_run(self, who: Who, s: dict[str, Any], status: str, *, activate: bool) -> None:
        """Records a run's outcome on the source; the second failure in a row, or a failure a day into a failing
        streak, raises the failing event once, with the source and its last error."""
        before = s.get("failing_since")
        in_row = await self.store.mark_synced(who.tenant_id, str(s["id"]), status, activate=activate)
        if status != "failed":
            await self.embed_now(who.tenant_id)
            return
        long_failing = isinstance(before, datetime) and datetime.now(UTC) - before >= FAILING_AFTER
        if in_row == FAILING_AFTER_RUNS or (long_failing and in_row > FAILING_AFTER_RUNS and in_row % 24 == 0):
            payload = {
                "sourceId": s["id"],
                "sourceName": s["name"],
                "owner": s["owner"],
                "failedRuns": in_row,
                "failingSince": _iso(before) if isinstance(before, datetime) else None,
            }
            await self.store.record_event(who.tenant_id, str(s["id"]), name=FAILING_EVENT, payload=payload)

    async def embed_now(self, tenant: str) -> int:
        """Embeds the tenant's units that have no vector yet, as a sync settles; a model that cannot answer leaves them
        to the embedding beat, and the sync is not failed for it."""
        if self.embedder is None or self.vectors is None:
            return 0
        try:
            return await embed_pending(self.vectors, self.embedder, tenant)
        except EmbedFailed as e:
            logger.warning("kb_embed_deferred", tenant=tenant, code=e.code)
            return 0

    async def start_rebuild(self, who: Who, s: dict[str, Any]) -> dict[str, Any] | None:
        """Rebuilds, in the background, every item of the source built under other settings: split again from its
        stored reading, or read again when the OCR mode changed. Nothing is fetched from where the item came from. The
        run holds the source's lease, so no sync runs beside it, and stops between two items when cancelled. None when
        no item needs it, or a sync holds the source now (that sync, or the next, rebuilds them)."""
        tenant, source_id = who.tenant_id, str(s["id"])
        stale = [
            i for i in await self.store.items(tenant, source_ids=[source_id]) if self.built_under_other_settings(s, i)
        ]
        if not stale or not await self.store.claim(tenant, source_id, until=datetime.now(UTC) + LEASE):
            return None
        run: dict[str, Any] = {
            "tenant_id": tenant,
            "id": new_id("run"),
            "source_id": source_id,
            "trigger": "settings",
            "started_at": datetime.now(UTC),
            "duration_sec": 0.0,
            "status": "running",
            "counts": {"total": len(stale), "checked": 0, "rebuilt": 0, "reading": 0, "failed": 0, "skipped": 0},
            "errors": [],
            "log": [],
            "started_by": who.email,
        }
        await self.store.add_run(run)
        task = asyncio.create_task(self._rebuild(who, s, run, stale))
        self.rebuilds.add(task)
        task.add_done_callback(self.rebuilds.discard)
        return _run(run)

    async def _rebuild(self, who: Who, s: dict[str, Any], run: dict[str, Any], stale: list[dict[str, Any]]) -> None:
        tenant, source_id, run_id = who.tenant_id, str(s["id"]), str(run["id"])
        counts: dict[str, int] = dict(run["counts"])
        log: list[str] = []
        errors: list[dict[str, Any]] = []
        status = "success"
        try:
            for item in stale:
                current = (await self.store.runs(tenant, run_id=run_id))[0]
                if current["cancelled_by"]:
                    status = "cancelled"
                    log.append(
                        f"Cancelled by {current['cancelled_by']} after {counts['checked']} of {counts['total']}."
                    )
                    break
                counts["checked"] += 1
                if not item["file_id"]:
                    # Content read through a connection's tools keeps no copy yet: it is rebuilt when next fetched.
                    counts["skipped"] += 1
                    log.append(f"{item['title']}: rebuilt at the next sync, which fetches it again")
                else:
                    found = Stored(str(item["file_id"]), str(item["path"]), str(item["mime"]), int(item["size"]),
                                   str(item["digest"]), False)  # fmt: skip
                    origin = Origin(str(item["path"]), str(item["title"])) if s["type"] != "file" else None
                    done = await self._read_file(
                        who, s, item, name=str(item["path"]), found=found, rebuild=True, origin=origin
                    )
                    outcome = {"indexed": "rebuilt", "reading": "reading"}.get(str(done["status"]), "failed")
                    counts[outcome] += 1
                    if outcome == "failed":
                        errors.append({"itemId": done["id"], "itemTitle": done["title"], "phase": "parse",
                                       "errorClass": done["error_class"], "message": done["error"]})  # fmt: skip
                await self.store.update_run(tenant, run_id, {"counts": dict(counts)})
            if status == "success" and counts["failed"]:
                status = "partial"
        except asyncio.CancelledError:
            status = "failed"
            log.append("Stopped when the service stopped; save the settings again or sync to finish.")
            raise
        finally:
            ended = datetime.now(UTC)
            await self.store.update_run(
                tenant,
                run_id,
                {
                    "status": status,
                    "counts": counts,
                    "errors": errors,
                    "log": log,
                    "finished_at": ended,
                    "duration_sec": round((ended - run["started_at"]).total_seconds(), 2),
                },
            )
            await self.store.release(tenant, source_id)
            if counts["rebuilt"]:
                _, by_source = await self._joined(tenant)
                await self.store.refreshed(tenant, by_source.get(source_id, []))
                await self.embed_now(tenant)

    async def cancel_run(self, who: Who, run_id: str) -> dict[str, Any]:
        """Asks a running rebuild to stop between two items; 409 when it is not running."""
        found = await self.store.runs(who.tenant_id, run_id=run_id)
        if not found:
            raise NotFound("No sync run with that id.")
        await self._changeable_source(who, str(found[0]["source_id"]))
        if not await self.store.cancel_run(who.tenant_id, run_id, by=who.email):
            raise Conflict("This run is not running.", code="run_not_running")
        return _run((await self.store.runs(who.tenant_id, run_id=run_id))[0])

    async def _sync(
        self, who: Who, s: dict[str, Any], *, full: bool, retry: bool, trigger: str | None = None
    ) -> dict[str, Any]:
        """Reads every file of the source and indexes what changed: a new name is a new document, a known name with
        different content is its next version, identical content is unchanged. `full` rebuilds every document from its
        content and `retry` rebuilds the failed ones, both keeping their version. One file failing does not stop the
        rest; its item says why. Every sync is recorded as a run."""
        source_id = s["id"]
        if s["status"] == "paused":
            raise Conflict(f"{s['name']} is paused; resume it to sync.", code="source_paused")
        started = datetime.now(UTC)
        settings = self.settings_of(s)
        items = {i["path"]: i for i in await self.store.items(who.tenant_id, source_ids=[source_id])}
        counts = {"listed": 0, "unchanged": 0, "upserted": 0, "deleted": 0, "failed": 0, "skipped": 0, "excluded": 0}
        errors: list[dict[str, Any]] = []
        log: list[str] = []
        # Each document is read from the last file uploaded under its name; an earlier file under the same name (left
        # by uploads before add_file replaced them) is dropped from the source, so it is neither indexed nor pending.
        latest: dict[str, Stored] = {}
        superseded: set[str] = set()
        uploaded: dict[str, str] = s.get("file_names") or {}
        counts["reading"] = 0
        for file_id in s["file_ids"]:
            try:
                found = await self.files.describe(who.tenant_id, source_team(s), file_id)
            except FileMissing:
                counts["listed"] += 1
                counts["failed"] += 1
                log.append(f"{file_id}: the file is no longer in storage")
                continue
            except FileNotScanned:
                # Stays pending on the source; the next sync after the scan reads it.
                counts["listed"] += 1
                counts["skipped"] += 1
                log.append(f"{uploaded.get(file_id, file_id)}: not scanned yet, so not read")
                continue
            # Indexed under the name it was uploaded under in this source (kb_0005), not the blob's first name.
            name = uploaded.get(file_id) or found.name
            if name in latest:
                superseded.add(latest[name].file_id)
            latest[name] = found
        await self.store.drop_files(who.tenant_id, source_id, superseded)
        excluded: list[str] = []
        for name, found in latest.items():
            counts["listed"] += 1
            existing = items.get(name)
            facts = ItemFacts(path=name, title=name, mime=found.mime, modified=started, size=found.size)
            if not (decision := evaluate_rules(settings.rules, facts)).included:
                counts["excluded"] += 1
                log.append(f"{name}: {decision.excluded_by}")
                if existing is not None:
                    excluded.append(str(existing["id"]))
                continue
            # files-service's digest, the key documents-service keeps the file's reading under.
            same = existing is not None and existing["digest"] == found.digest and existing["status"] != "reading"
            stale = existing is not None and self.built_under_other_settings(s, existing)
            if same and existing is not None and not (stale or full or (retry and existing["status"] == "failed")):
                counts["unchanged"] += 1
                continue
            if not same and any(i["digest"] == found.digest and i is not existing for i in items.values()):
                # The same content under another name in this source: indexed once.
                counts["skipped"] += 1
                log.append(f"{name}: the same content is already indexed in this source")
                continue
            item = await self._read_file(who, s, existing, name=name, found=found, rebuild=same)
            items[name] = item
            if item["status"] == "failed":
                counts["failed"] += 1
                errors.append(
                    {
                        "itemId": item["id"],
                        "itemTitle": item["title"],
                        "phase": "parse",
                        "errorClass": item["error_class"],
                        "message": item["error"],
                    }
                )
            elif item["status"] == "reading":
                counts["reading"] += 1
                log.append(f"{name}: being read (scanned pages take a while); it is indexed when the reading ends")
            else:
                counts["upserted"] += 1
        # An item a rule now excludes leaves search with its pieces; the file stays in the source.
        counts["deleted"] += await self.store.remove_items(who.tenant_id, excluded)
        status = (
            "failed" if counts["failed"] and not counts["upserted"] else "partial" if counts["failed"] else "success"
        )
        # A draft activates on its first sync that indexes something, as the source page promises; a sync that
        # indexed nothing (no files, or all failed) leaves it draft so its setup is finished first.
        indexed = counts["upserted"] > 0 or counts["unchanged"] > 0
        await self.settle_run(who, s, status, activate=indexed)
        _, by_source = await self._joined(who.tenant_id)
        if counts["upserted"] or counts["deleted"]:
            await self.store.refreshed(who.tenant_id, by_source.get(source_id, []))
        run: dict[str, Any] = {
            "tenant_id": who.tenant_id,
            "id": new_id("run"),
            "source_id": source_id,
            "trigger": trigger or ("full" if full else "retry" if retry else "manual"),
            "started_at": started,
            "duration_sec": round((datetime.now(UTC) - started).total_seconds(), 2),
            "status": status,
            "counts": counts,
            "errors": errors,
            "log": log,
            "started_by": who.email,
        }
        await self.store.add_run(run)
        return _run(run)

    def _chunks(
        self, who: Who, s: dict[str, Any], doc: ParsedDocument, *, item_id: str, version: int, title: str
    ) -> list[dict[str, Any]]:
        """The item's pieces under the source's settings, each with its index units and its mapped metadata."""
        settings = self.settings_of(s)
        result = split(doc, split_settings(settings))
        return pieces(who.tenant_id, item_id, version, title, result, self._metadata(s, doc))

    def _metadata(self, s: dict[str, Any], doc: ParsedDocument) -> dict[str, str]:
        mapped = resolve_metadata(
            self.settings_of(s).metadata_mapping,
            fields=doc.source.fields,
            collection=str(s["collection"]),
            source_owner=str(s["owner"]),
            source_sensitivity=s["sensitivity"],
        )
        return mapped.values

    async def _reindex(
        self,
        who: Who,
        s: dict[str, Any],
        existing: dict[str, Any],
        *,
        name: str,
        doc: ParsedDocument,
        read_with: str,
        title_given: str | None = None,
        lines: list[str] | None = None,
    ) -> dict[str, Any]:
        """The same content split again from its stored reading under its current version: no new version, no change
        row, and the file's bytes are not read again."""
        error: tuple[str, str] | None = None
        warning: str | None = None
        title, pages = title_given or doc.title or name, doc.source.page_count
        settings = self.settings_of(s)
        chunks = self._chunks(who, s, doc, item_id=existing["id"], version=existing["version"], title=title)
        if chunks:
            warning = _unread(doc)
        else:
            error = _empty(doc, settings.parsing.ocr)
        values = {
            "title": title,
            "page_count": pages,
            "status": "failed" if error else "indexed",
            "error_class": error[0] if error else None,
            "error": error[1] if error else None,
            "warning": None if error else warning,
            "chunk_count": len(chunks),
            "read_with": read_with,
            "lines": lines,
            "indexed_with": self.key_of(s),
            "content_digest": None if error else document_digest(doc, split_settings(settings)),
            "processed_at": datetime.now(UTC),
        }
        await self.store.reindex(who.tenant_id, existing["id"], values, chunks)
        return await self._duplicates(who, s, {**existing, **values})

    def built_under_other_settings(self, s: dict[str, Any], item: dict[str, Any]) -> bool:
        """Whether an indexed item's pieces were split, or its file read, under settings the source no longer has.
        An item indexed before items recorded their settings was split with its kind's defaults."""
        if item["status"] != "indexed":
            return False
        settings = self.settings_of(s)
        built = item.get("indexed_with") or index_key(stored(kind_of(s), None, ocr=self.ocr))
        read_ocr = str(item.get("read_with") or "").split(":")
        reread = s["type"] == "file" and len(read_ocr) > 1 and read_ocr[1] != settings.parsing.ocr
        return built != self.key_of(s) or reread

    async def _read_file(
        self,
        who: Who,
        s: dict[str, Any],
        existing: dict[str, Any] | None,
        *,
        name: str,
        found: Stored,
        rebuild: bool,
        origin: Origin | None = None,
    ) -> dict[str, Any]:
        """One file of a source from its reading: indexed when the reading is ready, marked reading while
        documents-service reads it in the background (or is out of reach), failed with the reader's reason. A file
        source's item is keyed by its name; a fetched item gives its `origin` (the system's id, title and marker)."""
        origin = origin or Origin(name)
        if self.readings is None:
            return await self._failed(who, s, existing, name=name, found=found, error=NO_READER, origin=origin)
        try:
            ocr = self.settings_of(s).parsing.ocr
            answer = await self.readings.reading(who.tenant_id, source_team(s), found.file_id, ocr=ocr)
        except DocumentsRefused as e:
            failed = ("parse", e.message)
            return await self._failed(who, s, existing, name=name, found=found, error=failed, origin=origin)
        except ServiceUnreachable:
            # The owner's rule: a sync waits for documents-service while it is down; the item stays queued.
            return await self._mark_reading(who, s, existing, name=name, found=found, origin=origin)
        status = answer.get("status")
        if status in READING_PENDING:
            return await self._mark_reading(who, s, existing, name=name, found=found, origin=origin)
        if status != "done":
            said: dict[str, Any] = answer.get("error") or {}
            reason = str(said.get("message") or "the file could not be read")
            return await self._failed(who, s, existing, name=name, found=found, error=("parse", reason), origin=origin)
        cleaning = self.settings_of(s).cleaning
        # A fetched item's fields (from its fetch, or kept on it for a rebuild) feed the metadata mapping.
        fields = cast(dict[str, str] | None, origin.extra.get("fields") or (existing or {}).get("fields"))
        doc = parsed_of(answer, fields=fields, furniture=cleaning.furniture, main_content=cleaning.main_content)
        # Each paragraph's digest is kept before lines repeated across the site are dropped, so they can be counted.
        lines = lines_of(doc)
        if cleaning.site_repeats:
            doc = without(doc, set(repeats_of(s)))
        if rebuild and existing is not None:
            return await self._reindex(
                who, s, existing, name=name, doc=doc, read_with=read_with(answer), title_given=origin.title, lines=lines
            )
        return await self._index(
            who, s, existing, file_id=found.file_id, name=name, mime=found.mime, doc=doc, size=found.size,
            digest=found.digest, read_with=read_with(answer), path=origin.path, extra={**origin.extra, "lines": lines},
            title_given=origin.title, allowed=origin.allowed,
        )  # fmt: skip

    async def _mark_reading(
        self, who: Who, s: dict[str, Any], existing: dict[str, Any] | None, *, name: str, found: Stored, origin: Origin
    ) -> dict[str, Any]:
        """The item waits for its reading; an indexed version keeps answering until the new one is indexed."""
        values = {"status": "reading", "digest": found.digest, "file_id": found.file_id, "mime": found.mime,
                  "size": found.size, "error_class": None, "error": None}  # fmt: skip
        if existing is not None:
            await self.store.update_item(who.tenant_id, existing["id"], values)
            return {**existing, **values}
        item = self._placeholder(who, s, name, found, origin) | values
        await self.store.add_item(who.tenant_id, item)
        return item

    async def _failed(
        self,
        who: Who,
        s: dict[str, Any],
        existing: dict[str, Any] | None,
        *,
        name: str,
        found: Stored,
        error: tuple[str, str],
        origin: Origin | None = None,
    ) -> dict[str, Any]:
        values = {"status": "failed", "error_class": error[0], "error": error[1], "digest": found.digest,
                  "file_id": found.file_id, "processed_at": datetime.now(UTC)}  # fmt: skip
        if existing is not None:
            await self.store.update_item(who.tenant_id, existing["id"], values)
            return {**existing, **values}
        item = self._placeholder(who, s, name, found, origin or Origin(name)) | values
        await self.store.add_item(who.tenant_id, item)
        return item

    def _placeholder(self, who: Who, s: dict[str, Any], name: str, found: Stored, origin: Origin) -> dict[str, Any]:
        """An item with no version yet: its first indexed version is 1."""
        return {
            "tenant_id": who.tenant_id, "id": new_id("itm"), "source_id": s["id"], "path": origin.path,
            "title": origin.title or name, "mime": found.mime, "size": found.size, "file_id": found.file_id,
            "digest": found.digest, "version": 0, "status": "reading", "chunk_count": 0, "owner": s["owner"],
            "created_at": datetime.now(UTC), **origin.extra,
        }  # fmt: skip

    async def finish_reading(self, who: Who, file_id: str) -> int:
        """Indexes the source items waiting on this file's reading, once documents-service has it (its
        reading.finished event, or the knowledge schedule asking again); the number of items it settled."""
        settled = 0
        for item in await self.store.reading_items(who.tenant_id, file_id=file_id):
            found_sources = await self.store.sources(who.tenant_id, [str(item["source_id"])])
            if not found_sources:
                continue
            source = found_sources[0]
            found = Stored(str(item["file_id"]), str(item["path"]), str(item["mime"]), int(item["size"]),
                           str(item["digest"]), False)  # fmt: skip
            # A fetched item keeps the system's id as its key and its own title; a file's title comes from its reading.
            origin = Origin(str(item["path"]), str(item["title"])) if source["type"] != "file" else None
            done = await self._read_file(
                who, source, item, name=str(item["path"]), found=found, rebuild=False, origin=origin
            )
            if done["status"] != "reading":
                settled += 1
                if done["status"] == "indexed":
                    await self.settle_run(who, source, "success", activate=True)
                    _, by_source = await self._joined(who.tenant_id)
                    await self.store.refreshed(who.tenant_id, by_source.get(str(source["id"]), []))
        return settled

    async def _index(
        self,
        who: Who,
        s: dict[str, Any],
        existing: dict[str, Any] | None,
        *,
        file_id: str,
        name: str,
        mime: str,
        digest: str,
        doc: ParsedDocument,
        size: int,
        read_with: str | None = None,
        path: str | None = None,
        extra: dict[str, Any] | None = None,
        title_given: str | None = None,
        allowed: list[str] | None = None,
    ) -> dict[str, Any]:
        """The item's next version from its reading's document (`doc`): every file and every fetched item is read by
        documents-service, never here. `path` keys the document in its source (a file's name, or the system's id for
        a fetched item), `extra` adds a fetched item's marker, parent and address, and `title_given` is the system's
        own title for it."""
        now = datetime.now(UTC)
        item_id = existing["id"] if existing else new_id("itm")
        version = (existing["version"] + 1) if existing else 1
        chunks: list[dict[str, Any]] = []
        error: tuple[str, str] | None = None
        warning: str | None = None
        settings = self.settings_of(s)
        title, pages = title_given or doc.title or name, doc.source.page_count
        chunks = self._chunks(who, s, doc, item_id=item_id, version=version, title=title)
        if chunks:
            warning = _unread(doc)
        else:
            error = _empty(doc, settings.parsing.ocr)
        item = {
            "tenant_id": who.tenant_id,
            "id": item_id,
            "source_id": s["id"],
            "path": path or name,
            "title": title,
            "mime": mime,
            "size": size,
            "file_id": file_id,
            "digest": digest,
            "version": version,
            "status": "failed" if error else "indexed",
            "error_class": error[0] if error else None,
            "error": error[1] if error else None,
            "warning": None if error else warning,
            "page_count": pages,
            "chunk_count": len(chunks),
            "owner": s["owner"],
            "created_at": existing["created_at"] if existing else now,
            "processed_at": now,
            "read_with": read_with,
            "indexed_with": None if error else self.key_of(s),
            "content_digest": None if error else document_digest(doc, split_settings(settings)),
            "duplicate_of": None,
            **(extra or {}),
        }
        version_row = {
            "tenant_id": who.tenant_id,
            "item_id": item_id,
            "version": version,
            "file_id": file_id,
            "digest": digest,
            "status": "current",
            "allowed": allowed,
            "created_by": who.email,
            "created_at": now,
        }
        change = None
        # An item that was only waiting for its first reading (version 0) has nothing to compare.
        if existing is not None and existing["version"] > 0:
            before = await self.store.chunks(who.tenant_id, item_id)
            change = _change(who, s, item, existing["version"], before, chunks, now)
        await self.store.index_version(who.tenant_id, item, version_row, chunks, new=existing is None, change=change)
        return await self._duplicates(who, s, item)

    async def _duplicates(self, who: Who, s: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        """An item whose cleaned text another indexed item in the same knowledge base already holds. Flagged (the
        default): the older one names the newer and leaves search, and both say so. Skipped: the newer one is kept out
        of search and says which item holds the text."""
        digest = item.get("content_digest")
        if item["status"] != "indexed" or not digest:
            return item
        same = await self.store.same_content(who.tenant_id, str(item["id"]), str(digest))
        if not same:
            return item
        names = ", ".join(sorted(str(d["title"]) for d in same))
        if self.settings_of(s).cleaning.duplicates == "skip":
            values = {"status": "skipped", "warning": f"Not indexed: the same text is already in {names}."}
            await self.store.update_item(who.tenant_id, str(item["id"]), values)
            return {**item, **values}
        for d in same:
            await self.store.update_item(
                who.tenant_id,
                str(d["id"]),
                {"duplicate_of": item["id"], "warning": f"Left out of search: {item['title']} has the same text."},
            )
        values = {"warning": f"Same text as {names}, which search now leaves out."}
        await self.store.update_item(who.tenant_id, str(item["id"]), values)
        return {**item, **values}

    # ── Retrieval ────────────────────────────────────────────────────────

    async def readable_bases(self, who: Who) -> list[dict[str, Any]]:
        """Every base of the tenant for a service, which checks its callers' grants itself; for a person, those of
        their team and those no team owns."""
        if who.caller is not None and who.caller.kind == "service":
            return await self.store.bases(who.tenant_id)
        return await self.store.team_bases(who.tenant_id, who.team_id)

    async def search(self, who: Who, kb_ids: list[str], question: str, *, limit: int | None = None) -> dict[str, Any]:
        """Passages for `question` across `kb_ids` in the caller's tenant, best first, by the bases' own retrieval
        settings; empty when nothing reaches the threshold. Unknown ids are refused, never silently searched as empty,
        and a base a person may not read is unknown to them; a retired base is skipped, so an agent that still names it
        answers from its other bases. `limit`, when given, caps the pieces below what the bases allow."""
        tenant = who.tenant_id
        readable = {b["id"]: b for b in await self.readable_bases(who)}
        retired = await self.store.retired(tenant, [k for k in kb_ids if k not in readable])
        if missing := [k for k in kb_ids if k not in readable and k not in retired]:
            raise NotFound(f"No knowledge base with id {missing[0]}.")
        live = [k for k in dict.fromkeys(kb_ids) if k in readable]
        how = search_settings([readable[k] for k in live], limit=limit)
        found = await self.retriever.search(tenant, live, question, how)
        return found_out(found)

    async def query(self, who: Who, kb_id: str, question: str) -> dict[str, Any]:
        """The query route and the console's Playground: the passages one knowledge base returns for a question, with
        each lane's score, which lanes ran, and the embedding tokens the question cost. No model writes an answer here;
        an answer is a kernel turn (agents-service), where the rule that withholds an uncited answer lives."""
        b = await self.store.base(who.tenant_id, kb_id)
        if b is None:
            raise NotFound("No knowledge base with that id.")
        if b["last_refreshed_at"] is None:
            raise Conflict("This knowledge base has not indexed anything yet; sync a source first.", code="not_indexed")
        started = datetime.now(UTC)
        found = await self.retriever.search(who.tenant_id, [kb_id], question, search_settings([b]))
        passages = found.passages
        sources = {s["id"]: s for s in await self.store.sources(who.tenant_id)}
        items = {i["id"]: i for i in await self.store.items(who.tenant_id)}

        def source_name(p: Passage) -> str:
            item = items.get(p.item_id)
            return sources[item["source_id"]]["name"] if item and item["source_id"] in sources else ""

        return {
            "id": new_id("qry"),
            "question": question,
            "matchers": [],
            "answer": passages[0].snippet if passages else b["retrieval"]["noAnswerMessage"],
            "citations": [
                {
                    "n": n + 1,
                    "documentId": p.item_id,
                    "title": p.title,
                    "section": p.section,
                    **({"page": p.page} if p.page else {}),
                    "version": f"v{p.version}",
                    "snippet": p.snippet,
                }
                for n, p in enumerate(passages)
            ],
            "chunks": [
                {
                    "chunkId": p.chunk_id or f"{p.item_id}:{n}",
                    "documentId": p.item_id,
                    "documentTitle": p.title,
                    "sourceName": source_name(p),
                    "score": p.score,
                    "lanes": p.lanes,
                    "location": _location(p.section, p.page),
                    "text": p.text,
                    "rejected": False,
                    "version": f"v{p.version}",
                }
                for n, p in enumerate(passages)
            ],
            **({"noAnswer": True} if not passages else {}),
            **found_out(found),
            "retrievalMs": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "synthesisMs": 0,
            "shape": "chunks",
        }

    async def embedding_coverage(self, who: Who, kb_id: str) -> dict[str, Any] | None:
        """How many of the base's units have a vector of the environment's model; None without one."""
        if self.embedder is None or self.vectors is None or not await self.vectors.ready():
            return None
        embedded, total = await self.vectors.coverage(
            who.tenant_id, [kb_id], model=self.embedder.model, width=self.embedder.width
        )
        return {"model": self.embedder.model, "width": self.embedder.width, "embedded": embedded, "units": total}

    # ── Runs, source settings, refresh ───────────────────────────────────

    async def source_runs(self, who: Who, source_id: str, *, page: int, page_size: int) -> dict[str, Any]:
        await self._source_row(who, source_id)
        rows = [_run(r) for r in await self.store.runs(who.tenant_id, source_id=source_id)]
        return page_of(rows, page=page, page_size=page_size, facets={"status": _facet(rows, "status")})

    async def get_run(self, who: Who, run_id: str) -> dict[str, Any]:
        found = await self.store.runs(who.tenant_id, run_id=run_id)
        if not found:
            raise NotFound("No sync run with that id.")
        return _run(found[0])

    async def update_source(self, who: Who, source_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        s = await self._changeable_source(who, source_id)
        values: dict[str, Any] = {}
        if patch.get("name") is not None:
            if not str(patch["name"]).strip():
                raise ValidationFailed("Give the source a name.")
            values["name"] = str(patch["name"]).strip()
        if patch.get("sensitivity") is not None:
            if patch["sensitivity"] not in SENSITIVITIES:
                raise ValidationFailed(f"Sensitivity is one of {', '.join(SENSITIVITIES)}.")
            values["sensitivity"] = patch["sensitivity"]
        if patch.get("owner") is not None:
            if not str(patch["owner"]).strip():
                raise ValidationFailed("A source always has an owner.")
            values["owner"] = str(patch["owner"]).strip()
        for key in ("collection", "tags"):
            if patch.get(key) is not None:
                values[key] = patch[key]
        given = {k: patch[k] for k in SETTINGS_KEYS if patch.get(k) is not None}
        before = self.settings_of(s)
        if given:
            values["settings"] = wire(self._merged(before, given))
        if values:
            entry = audit_entry(who, "knowledge.source.settings", "knowledge_source", source_id, s["name"], s, values)
            await self.store.update_source(who.tenant_id, source_id, values, audit=entry)
        _, by_source = await self._joined(who.tenant_id)
        after = {**s, **values}
        rebuild = None
        if given and rebuild_for(before, self.settings_of(after)) != "none":
            rebuild = await self.start_rebuild(who, after)
        return {**self._source(after, by_source.get(source_id, [])), "rebuild": rebuild}

    async def tombstones(self, who: Who, source_id: str) -> list[dict[str, Any]]:
        """The addresses removed after answering gone twice, with when and why; the next sync leaves them out."""
        s = await self._source_row(who, source_id)
        marks = cast(dict[str, dict[str, Any]], dict(s.get("config") or {}).get("tombstones") or {})
        return [{"id": k, "at": v.get("at"), "reason": v.get("reason")} for k, v in sorted(marks.items())]

    async def lift_tombstones(self, who: Who, source_id: str, ids: list[str]) -> list[dict[str, Any]]:
        """Lets the next sync take those addresses in again, if the source still lists them."""
        s = await self._changeable_source(who, source_id)
        cfg = dict(s.get("config") or {})
        marks = cast(dict[str, Any], dict(cfg.get("tombstones") or {}))
        if missing := [i for i in ids if i not in marks]:
            raise NotFound(f"No tombstone for {missing[0]}.")
        cfg["tombstones"] = {k: v for k, v in marks.items() if k not in ids}
        await self.store.update_source(who.tenant_id, source_id, {"config": cfg})
        return await self.tombstones(who, source_id)

    @staticmethod
    def _merged(current: SourceSettings, given: dict[str, Any]) -> SourceSettings:
        try:
            return merged(current, given)
        except InvalidSettings as e:
            raise ValidationFailed(str(e), code="invalid_settings") from e

    async def set_paused(self, who: Who, source_id: str, *, paused: bool) -> dict[str, Any]:
        s = await self._changeable_source(who, source_id)
        status = "paused" if paused else "active"
        await self.store.update_source(who.tenant_id, source_id, {"status": status})
        _, by_source = await self._joined(who.tenant_id)
        return self._source({**s, "status": status}, by_source.get(source_id, []))

    async def detach(self, who: Who, kb_id: str, source_id: str) -> dict[str, Any]:
        b = await self._changeable(who, kb_id)
        await self.store.detach(who.tenant_id, kb_id, source_id)
        by_kb, _ = await self._joined(who.tenant_id)
        return self._base(b, by_kb.get(kb_id, []), await self._counts(who.tenant_id))

    async def refresh(self, who: Who, kb_id: str, *, retry: bool = False) -> dict[str, Any]:
        """Syncs every source the knowledge base reads that is not paused (the knowledge base's owner keeps what it
        serves current, whoever owns each source); `retry` rebuilds only the failed documents."""
        b = await self._changeable(who, kb_id)
        by_kb, _ = await self._joined(who.tenant_id)
        for s in await self.store.sources(who.tenant_id, by_kb.get(kb_id, [])):
            if s["status"] != "paused":
                try:
                    await self._held_sync(who, s, full=False, retry=retry)
                except Conflict:
                    # Running now: that run brings it up to date.
                    continue
        fresh = await self.store.base(who.tenant_id, kb_id)
        return self._base(fresh or b, by_kb.get(kb_id, []), await self._counts(who.tenant_id))

    # ── Item review and lookups ──────────────────────────────────────────

    async def _changeable_item(self, who: Who, item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        found = await self.store.items(who.tenant_id, item_id=item_id)
        if not found:
            raise NotFound("No item with that id.")
        i = found[0]
        s = await self._source_row(who, i["source_id"])
        self._may_change(who, s["team_id"], i["title"])
        return i, s

    async def verify_item(self, who: Who, item_id: str, *, verified: bool) -> dict[str, Any]:
        i, s = await self._changeable_item(who, item_id)
        values = {
            "verified": verified,
            "verified_by": who.email if verified else None,
            "verified_at": datetime.now(UTC) if verified else None,
        }
        await self.store.update_item(who.tenant_id, item_id, values)
        return self._item({**i, **values}, s)

    async def set_item_owner(self, who: Who, item_id: str, owner: str) -> dict[str, Any]:
        if not owner.strip():
            raise ValidationFailed("A document always has an owner.")
        i, s = await self._changeable_item(who, item_id)
        await self.store.update_item(who.tenant_id, item_id, {"owner": owner.strip()})
        return self._item({**i, "owner": owner.strip()}, s)

    async def lookups(self, who: Who) -> dict[str, list[str]]:
        bases = await self.store.bases(who.tenant_id)
        sources = await self.store.sources(who.tenant_id)
        items = await self.store.items(who.tenant_id)
        owners = {b["owner"] for b in bases} | {s["owner"] for s in sources} | {i["owner"] for i in items}
        tags = {t for s in sources for t in s["tags"]}
        collections = {c for b in bases for c in b["collections"]} | {s["collection"] for s in sources}
        return {
            "owners": sorted(o for o in owners if o),
            "tags": sorted(tags),
            "collections": sorted(c for c in collections if c),
        }

    # ── Changes ──────────────────────────────────────────────────────────

    async def _change_out(self, who: Who, ch: dict[str, Any]) -> dict[str, Any]:
        sources = {s["id"]: s for s in await self.store.sources(who.tenant_id)}
        bases = {b["id"]: b for b in await self.store.bases(who.tenant_id)}
        _, by_source = await self._joined(who.tenant_id)
        s = sources.get(ch["source_id"])
        return {
            "id": ch["id"],
            "summary": f"{ch['title']} changed from v{ch['from_version']} to v{ch['to_version']}",
            "origin": "source_sync",
            "proposedBy": ch["changed_by"],
            "rationale": "A newer file replaced the document when its source was synced.",
            "documentId": ch["item_id"],
            "documentTitle": ch["title"],
            "sourceId": ch["source_id"],
            "sourceName": s["name"] if s else "",
            "section": ch["section"],
            "kbs": [{"id": k, "name": bases[k]["name"]} for k in by_source.get(ch["source_id"], []) if k in bases],
            "fromVersion": f"v{ch['from_version']}",
            "toVersion": f"v{ch['to_version']}",
            "before": ch["before"],
            "after": ch["after"],
            "trust": "changed",
            "freshness": "fresh",
            "reviewBy": "",
            "citedBy": [],
            "owner": s["owner"] if s else "",
            # A sync applies the change when it runs; there is nothing left to decide.
            "canDecide": False,
            "status": "approved",
            "createdAt": _iso(ch["changed_at"]),
            "decidedAt": _iso(ch["changed_at"]),
            "decidedBy": ch["changed_by"],
        }

    async def list_changes(
        self, who: Who, *, view: str, kb_id: str | None, page: int, page_size: int, search: str | None
    ) -> dict[str, Any]:
        item_ids: list[str] | None = None
        if kb_id is not None:
            by_kb, _ = await self._joined(who.tenant_id)
            item_ids = [i["id"] for i in await self.store.items(who.tenant_id, source_ids=by_kb.get(kb_id, []))]
        rows = [
            await self._change_out(who, ch)
            for ch in await self.store.changes(who.tenant_id, item_ids=item_ids)
            if _matches(search, ch["title"], ch["section"])
        ]
        # Source syncs are applied when they run, so every row is resolved; nothing waits on anyone.
        shown = rows if view in ("resolved", "all") else []
        listed = page_of(shown, page=page, page_size=page_size, facets={"origin": _facet(rows, "origin")})
        return {**listed, "viewCounts": {"mine": 0, "open": 0, "conflicts": 0, "resolved": len(rows)}}

    async def get_change(self, who: Who, change_id: str) -> dict[str, Any]:
        found = [c for c in await self.store.changes(who.tenant_id) if c["id"] == change_id]
        if not found:
            raise NotFound("No change with that id.")
        return await self._change_out(who, found[0])

    # ── Items and documents ──────────────────────────────────────────────

    def _item(self, i: dict[str, Any], s: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": i["id"],
            "sourceId": i["source_id"],
            "externalId": i["file_id"],
            "title": i["title"],
            "mimeType": i["mime"],
            "path": i["path"],
            "modifiedAt": _iso(i["processed_at"] or i["created_at"]),
            **({"processedAt": _iso(i["processed_at"])} if i["processed_at"] else {}),
            "sizeBytes": i["size"],
            # The console's word for a document being read is processing.
            "status": SHOWN_STATUS.get(i["status"], i["status"]),
            **({"errorClass": i["error_class"], "error": i["error"]} if i["error_class"] else {}),
            **({"warning": i["warning"]} if i.get("warning") else {}),
            **({"duplicateOf": i["duplicate_of"]} if i.get("duplicate_of") else {}),
            **({"folder": i["folder"]} if i.get("folder") else {}),
            "chunkCount": i["chunk_count"],
            "tags": s["tags"],
            "metadata": {},
            "acl": [],
            "owner": i["owner"],
            "version": f"v{i['version']}",
            "effectiveDate": (i["processed_at"] or i["created_at"]).date().isoformat(),
            "reviewBy": "",
            "sensitivity": s["sensitivity"],
            "collection": s["collection"],
            "verified": bool(i.get("verified")),
            "queries30d": 0,
            **({"pageCount": i["page_count"]} if i["page_count"] else {}),
            "fileId": i["file_id"],
            "digest": i["digest"],
            "family": i["id"],
            "versionStatus": "current",
        }

    async def source_items(
        self, who: Who, source_id: str, *, page: int, page_size: int, search: str | None
    ) -> dict[str, Any]:
        s = await self._source_row(who, source_id)
        rows = [
            self._item(i, s)
            for i in await self.store.items(who.tenant_id, source_ids=[source_id])
            if _matches(search, i["title"], i["path"])
        ]
        return page_of(rows, page=page, page_size=page_size, facets={"status": _facet(rows, "status")})

    async def add_page(self, who: Who, kb_id: str, title: str, text: str) -> dict[str, Any]:
        """A page written in the console: a titled text, stored as a Markdown file in the base's own pages source
        (made and attached the first time), synced at once, and returned as its document. A page under a title the
        base already has is that page's next version."""
        title, text = title.strip(), text.strip()
        if not title:
            raise ValidationFailed("Give the page a title.")
        if not text:
            raise ValidationFailed("Write the page's text.")
        b = await self._changeable(who, kb_id)
        by_kb, _ = await self._joined(who.tenant_id)
        name = f"{b['name']} pages"
        attached = await self.store.sources(who.tenant_id, by_kb.get(kb_id, []))
        source = next((x for x in attached if x["name"] == name), None)
        if source is None:
            source = await self.create_source(
                who, {"type": "file", "name": name, "collection": "Pages", "owner": b["owner"], "kbIds": [kb_id]}
            )
        path = f"{_slug(title) or 'page'}.md"
        body = f"# {title}\n\n{text}\n".encode()
        await self.upload(who, str(source["id"]), body, name=path, mime="text/markdown")
        await self.sync(who, str(source["id"]))
        found = await self.store.sources(who.tenant_id, [str(source["id"])])
        item = next(
            i for i in await self.store.items(who.tenant_id, source_ids=[str(source["id"])]) if i["path"] == path
        )
        return self._item(item, found[0])

    async def add_documents(self, who: Who, kb_id: str, file_ids: list[str]) -> dict[str, Any]:
        """Files from Files added to the base: into its own documents source, made and attached the first
        time, then synced at once, which also activates the source. Returns the source id, the files and the run."""
        b = await self._changeable(who, kb_id)
        by_kb, _ = await self._joined(who.tenant_id)
        own = b.get("documents_source_id")
        source = None
        if own and own in by_kb.get(kb_id, []):
            source = (await self.store.sources(who.tenant_id, [str(own)]) or [None])[0]
        made = source is None
        if source is None:
            source = await self.create_source(
                who,
                {
                    "type": "file",
                    "name": f"{b['name']} documents",
                    "collection": "Documents",
                    "owner": b["owner"],
                    "kbIds": [kb_id],
                },
            )
        try:
            added = await self.add_files(who, str(source["id"]), file_ids)
        except (UnknownFile, Conflict):
            # Files records a reference against the source, so it is made before the check; a refused first add must
            # not leave the base an empty documents source.
            if made:
                await self.store.remove_source(who.tenant_id, str(source["id"]))
            raise
        if made:
            await self.store.update_base(who.tenant_id, kb_id, {"documents_source_id": str(source["id"])})
        run = await self.sync(who, str(source["id"]))
        return {"sourceId": source["id"], "files": added, "run": run}

    async def documents(self, who: Who, kb_id: str, *, page: int, page_size: int, search: str | None) -> dict[str, Any]:
        if await self.store.base(who.tenant_id, kb_id) is None:
            raise NotFound("No knowledge base with that id.")
        by_kb, _ = await self._joined(who.tenant_id)
        sources = {s["id"]: s for s in await self.store.sources(who.tenant_id, by_kb.get(kb_id, []))}
        rows = [
            {
                **self._item(i, sources[i["source_id"]]),
                "sourceName": sources[i["source_id"]]["name"],
                "freshness": "fresh",
            }
            for i in await self.store.items(who.tenant_id, source_ids=list(sources))
            if _matches(search, i["title"], i["path"])
        ]
        return page_of(rows, page=page, page_size=page_size, facets={"status": _facet(rows, "status")})

    async def _reading_summary(self, who: Who, s: dict[str, Any], i: dict[str, Any]) -> dict[str, Any] | None:
        """How the item's file was read and what cleaning removed, page by page, from its stored reading; None for an
        item with no file or while documents-service has no finished reading for it."""
        if self.readings is None or not i.get("file_id"):
            return None
        settings = self.settings_of(s)
        ocr = settings.parsing.ocr
        try:
            answer = await self.readings.reading(who.tenant_id, source_team(s), str(i["file_id"]), ocr=ocr)
        except (DocumentsRefused, ServiceUnreachable):
            return None
        if answer.get("status") != "done":
            return None
        cleaning = settings.cleaning
        pages = cast(list[dict[str, Any]], answer.get("pages") or [])
        blocks_of = [cast(list[dict[str, Any]], p.get("blocks") or []) for p in pages]
        has_main = cleaning.main_content and any(b.get("main") for blocks in blocks_of for b in blocks)

        def dropped(b: dict[str, Any]) -> bool:
            if cleaning.furniture and b.get("furniture"):
                return True
            return has_main and not b.get("main") and b.get("kind") != "title"

        out: list[dict[str, Any]] = []
        for page, blocks in zip(pages, blocks_of, strict=True):
            kinds: dict[str, int] = {}
            for b in blocks:
                if not dropped(b):
                    kinds[str(b.get("kind"))] = kinds.get(str(b.get("kind")), 0) + 1
            quality = cast(dict[str, Any], page.get("ocr") or {})
            out.append(
                {
                    "number": page.get("number"),
                    "readBy": page.get("source"),
                    "blocks": kinds,
                    "removedChars": sum(len(str(b.get("text") or "")) for b in blocks if dropped(b)),
                    **({"ocrConfidence": quality.get("mean")} if quality else {}),
                }
            )
        return {"readerVersion": answer.get("readerVersion"), "ocr": ocr, "pages": out}

    async def item(self, who: Who, item_id: str) -> dict[str, Any]:
        found = await self.store.items(who.tenant_id, item_id=item_id)
        if not found:
            raise NotFound("No item with that id.")
        i = found[0]
        s = await self._source_row(who, i["source_id"])
        chunks = await self.store.chunks(who.tenant_id, item_id)
        searched: dict[str, list[dict[str, Any]]] = {}
        for u in await self.store.units(who.tenant_id, item_id):
            searched.setdefault(str(u["chunk_id"]), []).append({"kind": u["kind"], "text": u["text"]})
        versions = await self.store.versions(who.tenant_id, item_id)
        settings = self.settings_of(s)
        return {
            **self._item(i, s),
            "reading": await self._reading_summary(who, s, i),
            "settingsUsed": {
                "preset": settings.ingest.preset,
                "strategies": settings.ingest.strategies,
                "indexedWith": i.get("indexed_with"),
                "current": not self.built_under_other_settings(s, i),
            },
            "sourceName": s["name"],
            "sourceType": s["type"],
            "detail": {
                "content": "\n\n".join(c["text"] for c in chunks),
                "chunks": [
                    {
                        "index": c["position"],
                        "tokens": c["tokens"],
                        "location": _location(c["section"], c["page"]),
                        **({"page": c["page"]} if c["page"] else {}),
                        "kind": "content",
                        "text": c["text"],
                        # What search matches for this piece: its own text, its children and its questions.
                        "units": searched.get(str(c["id"]), []),
                        "metadata": c["metadata"] or {},
                    }
                    for c in chunks
                ],
                "revisions": [],
                "versions": [
                    {
                        "itemId": item_id,
                        "title": i["title"],
                        "version": f"v{v['version']}",
                        "effectiveDate": v["created_at"].date().isoformat(),
                        "status": v["status"],
                        "digest": v["digest"],
                        "sourceName": s["name"],
                        # Who the source system lets see this version; stored, not yet enforced.
                        **({"allowed": v["allowed"]} if v.get("allowed") else {}),
                    }
                    for v in versions
                ],
            },
        }


def _change(  # noqa: PLR0917 - one call site, every argument a different part of the change
    who: Who,
    s: dict[str, Any],
    item: dict[str, Any],
    from_version: int,
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    at: datetime,
) -> dict[str, Any]:
    """The change a re-sync made: the first section whose text differs, before and after."""
    old = {c["section"]: c["text"] for c in reversed(before)}
    new = {c["section"]: c["text"] for c in reversed(after)}
    section = next((k for k in [*new, *old] if old.get(k) != new.get(k)), "")
    return {
        "tenant_id": who.tenant_id,
        "id": new_id("chg"),
        "item_id": item["id"],
        "source_id": s["id"],
        "title": item["title"],
        "section": section,
        "from_version": from_version,
        "to_version": item["version"],
        "before": old.get(section, ""),
        "after": new.get(section, ""),
        "changed_by": who.email,
        "changed_at": at,
    }


# How the audit log names each kind of record a settings change is about.
AUDITED = {"knowledge_base": "knowledge base", "knowledge_source": "source"}


def audit_entry(  # noqa: PLR0917 - each argument a different part of the entry
    who: Who,
    action: str,
    target_kind: str,
    target_id: str,
    name: str,
    before: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any] | None:
    """The audit entry for a settings change: who made it, which fields changed, and each field before and after
    (for a nested setting, its changed keys). None when nothing changed. The seed, with no caller, is not audited."""
    if who.caller is None:
        return None
    changes: dict[str, Any] = {}
    for key, after in values.items():
        old = before.get(key)
        if old == after:
            continue
        if isinstance(old, dict) and isinstance(after, dict):
            was, now = cast(dict[str, Any], old), cast(dict[str, Any], after)
            keys = sorted(k for k in {*was, *now} if was.get(k) != now.get(k))
            changes[key] = {k: {"from": was.get(k), "to": now.get(k)} for k in keys}
        else:
            changes[key] = {"from": old, "to": after}
    if not changes:
        return None
    return {
        "actor": who.caller.sub,
        "action": action,
        "target_kind": target_kind,
        "target_id": target_id,
        "summary": f"Changed the settings of {AUDITED[target_kind]} {name}: {', '.join(sorted(changes))}",
        "detail": {"name": name, "changes": changes},
    }


def pieces(  # noqa: PLR0917 - each argument a different part of the piece rows
    tenant: str, item_id: str, version: int, title: str, result: SplitResult, metadata: dict[str, str]
) -> list[dict[str, Any]]:
    """A split as the rows kb_chunks and kb_units hold: each piece once, with the units it is searched as (its own
    text with its context header, its children, its questions), so a match on any unit cites the piece."""
    rows: list[dict[str, Any]] = []
    ids = [new_id("chk") for _ in result.chunks]
    units: dict[int, list[dict[str, Any]]] = {}
    for unit in result.index_units():
        chunk = result.chunks[unit.chunk_index]
        heading = " ".join(p for p in (title, " > ".join(chunk.section_path)) if p)
        mine = units.setdefault(unit.chunk_index, [])
        mine.append(
            {
                "tenant_id": tenant,
                "id": new_id("unt"),
                "chunk_id": ids[unit.chunk_index],
                "item_id": item_id,
                "kind": unit.kind,
                "position": len(mine),
                "heading": heading[:800],
                "text": unit.indexed_text,
            }
        )
    for n, c in enumerate(result.chunks):
        rows.append(
            {
                "tenant_id": tenant,
                "id": ids[n],
                "item_id": item_id,
                "version": version,
                "position": n,
                "title": title,
                "section": " > ".join(c.section_path),
                "page": c.page,
                "tokens": c.tokens,
                "text": c.text,
                "metadata": {**metadata, **c.metadata} or None,
                "units": units.get(c.index, []),
            }
        )
    return rows


def _run(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "sourceId": r["source_id"],
        "trigger": r["trigger"],
        "startedAt": _iso(r["started_at"]),
        "durationSec": r["duration_sec"],
        "status": r["status"],
        "counts": r["counts"],
        "phases": [],
        "errors": r["errors"],
        "log": r["log"],
        **({"finishedAt": _iso(r["finished_at"])} if r.get("finished_at") else {}),
        **({"cancelledBy": r["cancelled_by"]} if r.get("cancelled_by") else {}),
    }


def health_of(s: dict[str, Any]) -> dict[str, Any]:
    """A source's health in one place: never synced, healthy, failing (since when, for how many days) or waiting for
    its connection to be signed in again."""
    cfg = dict(s.get("config") or {})
    since: datetime | None = s.get("failing_since")
    good: datetime | None = s.get("last_good_sync_at")
    reconnect = cfg.get("paused") == "needs_reconnect"
    state = (
        "needs_reconnect"
        if reconnect
        else "failing"
        if since
        else "healthy"
        if good or s.get("last_sync_at")
        else "never"
    )
    return {
        "state": state,
        **({"lastGoodSyncAt": _iso(good)} if good else {}),
        **({"failingSince": _iso(since)} if since else {}),
        "daysFailing": (datetime.now(UTC) - since).days if since else 0,
        "failedRuns": int(s.get("failures_in_row") or 0),
        "tombstoned": len(cast(dict[str, Any], cfg.get("tombstones") or {})),
    }


def kind_of(s: dict[str, Any]) -> str:
    """The kind a source's defaults are chosen by: a plugin source whose items are one website's pages is `web`."""
    if s["type"] == "tool" and dict(s.get("config") or {}).get("site"):
        return "web"
    return str(s["type"])


def repeats_of(s: dict[str, Any]) -> list[str]:
    """The lines last found repeated across the source's pages."""
    found = cast(list[Any], dict(s.get("config") or {}).get("repeats") or [])
    return [str(d) for d in found]


def _empty(doc: ParsedDocument, ocr: str) -> tuple[str, str]:
    """Why a read document gave nothing to index."""
    if doc.pages_without_text:
        how = "OCR is off for this source" if ocr == "off" else "not even by OCR"
        return _no_text(f"{len(doc.pages_without_text)} pages have no text that could be read ({how}).")
    return ("parse", "The document has no text to index.")


def _pages(pages: list[int]) -> str:
    listed = ", ".join(str(p) for p in pages[:10]) + (f" and {len(pages) - 10} more" if len(pages) > 10 else "")
    return f"Page{'s' if len(pages) > 1 else ''} {listed}"


def _unread(doc: ParsedDocument) -> str | None:
    """What an indexed document left unread (pages with no text that could be read), and which pages were read by
    OCR, so a person checks those against the file."""
    said: list[str] = []
    pages = doc.pages_without_text
    if pages:
        many = len(pages) > 1
        said.append(f"{_pages(pages)} {'have' if many else 'has'} no text that could be read, so agents cannot cite "
                    f"{'them' if many else 'it'}.")  # fmt: skip
    if doc.ocr_pages:
        said.append(f"{_pages(doc.ocr_pages)} {'were' if len(doc.ocr_pages) > 1 else 'was'} read by OCR; check "
                    "a citation from it against the file.")  # fmt: skip
    said += [w for w in doc.warnings if "was not read" not in w]
    return " ".join(said) or None


class UnknownFile(ApiError):
    status = 404
    code = "file_not_found"


def _location(section: str, page: int | None) -> str:
    return ", ".join(p for p in (f"p. {page}" if page else "", section) if p)


def search_settings(bases: list[dict[str, Any]], *, limit: int | None = None) -> Search:
    """One search over several bases: the lanes any of them asks for, the lowest threshold, the mean weight toward
    meaning and the largest piece limit, so no base gets less than it asks; `limit` caps the pieces further."""
    if not bases:
        return Search(limit=limit or int(DEFAULT_RETRIEVAL["chunkLimit"]))
    settings = [{**DEFAULT_RETRIEVAL, **dict(b.get("retrieval") or {})} for b in bases]
    lanes: tuple[Lane, ...] = tuple(dict.fromkeys(lane for r in settings for lane in lanes_for(str(r["searchMode"]))))
    most = max(int(r["chunkLimit"]) for r in settings)
    return Search(
        lanes=lanes,
        threshold=min(float(r["threshold"]) for r in settings),
        weight=sum(float(r["hybridWeight"]) for r in settings) / len(settings),
        limit=min(most, limit) if limit else most,
    )


def found_out(found: Found) -> dict[str, Any]:
    return {
        "passages": [passage_out(p) for p in found.passages],
        "lanes": found.lanes_out(),
        "cost": {"embeddingTokens": found.embedding_tokens},
    }


def passage_out(p: Passage) -> dict[str, Any]:
    return {
        "kbId": p.kb_id,
        "itemId": p.item_id,
        "version": f"v{p.version}",
        "title": p.title,
        "section": p.section,
        **({"page": p.page} if p.page else {}),
        "snippet": p.snippet,
        "text": p.text,
        "score": p.score,
        **({"fileId": p.file_id} if p.file_id else {}),
        **({"url": p.url} if p.url else {}),
        "matched": p.matched,
        "lanes": p.lanes,
        "verified": p.verified,
    }
