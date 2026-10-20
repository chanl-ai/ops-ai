"""Knowledge bases and sources as the console reads them (apps/console/src/lib/types/knowledge.ts): rows with joined
names, details with attached sources, and lists paged and filtered on the server.

Fields this slice does not run yet (access settings, precedence, automation, schedules) are served with the values a
new knowledge base or source starts with, so the console's pages render without a mock;
.codeloop/wiki/concepts/knowledge.md section 6 is the designed surface and docs/services/kb-service/overview.md says
which part is built.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from ops_access import can, require_provisioner
from ops_identity import Principal
from ops_ingest import IngestSettings, parse, split
from ops_ingest.parsers import TooLargeError, UnsupportedFormatError
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, ValidationFailed
from ops_service_kit.http import options_page, options_window
from ops_service_kit.ids import new_id

from .agents import AgentDirectory, Usage
from .files import FileIntake, FileMissing, FileNotScanned
from .retrieval import Passage, Retriever
from .store import KnowledgeStore

# Keyword search is what the demo adapter runs (Postgres full-text, docs/services/kb-service/overview.md); the other
# fields are the console's defaults for a new knowledge base.
DEFAULT_RETRIEVAL: dict[str, Any] = {
    "searchMode": "keyword",
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
DEFAULT_INGEST: dict[str, Any] = {
    "preset": "policy_manual",
    "strategies": ["structure", "context_headers"],
    "size": 400,
    "overlap": 40,
    "childSize": 120,
    "questionsPerSection": 0,
    "columns": [],
    "model": "bank-standard",
    "approval": {"status": "not_needed", "approvedSteps": []},
}
SOURCE_TYPES_IN_PHASE = ("file",)
SENSITIVITIES = ("internal", "confidential", "restricted")
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class Who:
    tenant_id: str
    email: str
    team_id: str | None
    # The verified caller, which `ops_access.can` decides on (c-149). None for the seed, which acts as the system.
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
        """Only the provisioning service sets `templateId` or `protection` (c-180); the seed, with no caller, may."""
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


# Headings become sections; each chunk is prefixed with its title and section path, so a passage found out of
# context still says where it came from. No AI step runs at ingest.
INGEST = IngestSettings(preset="policy_manual", strategies=["structure", "context_headers"], size=400, overlap=40)


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
        "itemsPending": counts.get("pending", 0) + max(len(s["file_ids"]) - synced, 0),
    }


class KnowledgeService:
    def __init__(self, store: KnowledgeStore, files: FileIntake, retriever: Retriever, agents: AgentDirectory) -> None:
        self.store = store
        self.files = files
        self.retriever = retriever
        self.agents = agents

    # ── Serialising ──────────────────────────────────────────────────────

    def _source(self, s: dict[str, Any], used_by: list[str]) -> dict[str, Any]:
        return {
            "id": s["id"],
            "type": s["type"],
            "name": s["name"],
            "scopeSummary": f"{len(s['file_ids'])} uploaded files",
            "config": {"fileIds": s["file_ids"]},
            "parsing": {"ocr": False, "tables": False, "vision": False},
            "ingest": DEFAULT_INGEST,
            "rules": [],
            "metadataMapping": [],
            "tags": s["tags"],
            "titleFrom": "heading",
            "permissions": {"mode": "workspace"},
            "schedule": {"kind": "manual"},
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

    async def _counts(self, tenant: str) -> dict[str, dict[str, int]]:
        """Each source's documents by status and its indexed chunks, from its items."""
        return {str(x["id"]): x["item_counts"] for x in await self.store.sources(tenant)}

    def _base(self, b: dict[str, Any], source_ids: list[str], counts: dict[str, dict[str, int]]) -> dict[str, Any]:
        mine = [counts.get(sid, {}) for sid in source_ids]
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
        Knowledge is shared by the team (owner decision, 2026-10-17); `owner` names who answers for the content, not
        who may change it. Viewers and reviewers get 403; the decision is `can()`'s (c-149). A system record is
        changed by the provisioning service only (c-180)."""
        who.require_builder(
            team_id, f"{'delete' if step == 'delete' else 'change'} {what}", step, protection=protection
        )

    def _rights(self, who: Who, team_id: str | None, what: str, protection: str | None) -> dict[str, bool]:
        """`canEdit`, `canDelete` and `canPublish` for a detail response (c-216), from the check the write routes run,
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
            await self.store.update_base(who.tenant_id, kb_id, values)
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
        rows = [
            {
                **self._source(s, by_source.get(s["id"], [])),
                "usedBy": [{"id": k, "name": bases[k]["name"]} for k in by_source.get(s["id"], []) if k in bases],
                "running": False,
            }
            for s in sorted(sources, key=lambda s: s["created_at"], reverse=True)
            if _matches(search, s["name"], s["owner"], s["collection"])
        ]
        facets = {"type": _facet(rows, "type"), "status": _facet(rows, "status")}
        return page_of(rows, page=page, page_size=page_size, facets=facets)

    async def get_source(self, who: Who, source_id: str) -> dict[str, Any]:
        found = await self.store.sources(who.tenant_id, [source_id])
        if not found:
            raise NotFound("No source with that id.")
        s = found[0]
        _, by_source = await self._joined(who.tenant_id)
        readers = [b for b in await self.store.bases(who.tenant_id) if b["id"] in by_source.get(source_id, [])]
        recent = [_run(r) for r in (await self.store.runs(who.tenant_id, source_id=source_id))[:5]]
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
            **self._rights(who, s["team_id"], s["name"], s.get("protection")),
            # The Last sync tile's "Took ..." hint; absent until a first run.
            **({"lastRunDurationSec": recent[0]["durationSec"]} if recent else {}),
            "errorGroups": [],
            "itemCount": 0,
            "reindexNeeded": False,
            "requiredMetadata": [],
            "governance": {"excluded": 0, "held": 0, "duplicates": 0, "superseded": 0},
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
        # Files named at creation are checked and referenced like any added later, before the source exists.
        names = [await self._use_file(who, row, f) for f in dict.fromkeys(i.get("fileIds") or [])]
        row["file_ids"] = [f for f, _ in names]
        row["file_names"] = dict(names)
        await self.store.create_source(row, kb_ids)
        return self._source(row, kb_ids)

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
        return await self._sync(who, s, full=full, retry=retry)

    async def _sync(self, who: Who, s: dict[str, Any], *, full: bool, retry: bool) -> dict[str, Any]:
        """Reads every file of the source and indexes what changed: a new name is a new document, a known name with
        different content is its next version, identical content is unchanged. `full` rebuilds every document from its
        content and `retry` rebuilds the failed ones, both keeping their version. One file failing does not stop the
        rest; its item says why. Every sync is recorded as a run."""
        source_id = s["id"]
        if s["status"] == "paused":
            raise Conflict(f"{s['name']} is paused; resume it to sync.", code="source_paused")
        started = datetime.now(UTC)
        items = {i["path"]: i for i in await self.store.items(who.tenant_id, source_ids=[source_id])}
        counts = {"listed": 0, "unchanged": 0, "upserted": 0, "deleted": 0, "failed": 0, "skipped": 0}
        errors: list[dict[str, Any]] = []
        log: list[str] = []
        # Each document is read from the last file uploaded under its name; an earlier file under the same name (left
        # by uploads before add_file replaced them) is dropped from the source, so it is neither indexed nor pending.
        latest: dict[str, tuple[str, str, bytes]] = {}
        superseded: set[str] = set()
        uploaded: dict[str, str] = s.get("file_names") or {}
        for file_id in s["file_ids"]:
            try:
                stored_name, mime, data = await self.files.read(who.tenant_id, source_team(s), file_id)
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
            name = uploaded.get(file_id) or stored_name
            if name in latest:
                superseded.add(latest[name][0])
            latest[name] = (file_id, mime, data)
        await self.store.drop_files(who.tenant_id, source_id, superseded)
        for name, (file_id, mime, data) in latest.items():
            counts["listed"] += 1
            digest = hashlib.sha256(data).hexdigest()
            existing = items.get(name)
            if existing is not None and existing["digest"] == digest:
                if full or (retry and existing["status"] == "failed"):
                    item = await self._reindex(who, s, existing, name=name, mime=mime, data=data)
                    items[name] = item
                    counts["failed" if item["status"] == "failed" else "upserted"] += 1
                else:
                    counts["unchanged"] += 1
                continue
            if any(i["digest"] == digest for i in items.values()):
                # The same content under another name in this source: indexed once.
                counts["skipped"] += 1
                log.append(f"{name}: the same content is already indexed in this source")
                continue
            item = await self._index(who, s, existing, file_id=file_id, name=name, mime=mime, data=data, digest=digest)
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
            else:
                counts["upserted"] += 1
        status = (
            "failed" if counts["failed"] and not counts["upserted"] else "partial" if counts["failed"] else "success"
        )
        # A draft activates on its first sync that indexes something, as the source page promises; a sync that
        # indexed nothing (no files, or all failed) leaves it draft so its setup is finished first.
        indexed = counts["upserted"] > 0 or counts["unchanged"] > 0
        await self.store.mark_synced(who.tenant_id, source_id, status, activate=indexed)
        _, by_source = await self._joined(who.tenant_id)
        if counts["upserted"]:
            await self.store.refreshed(who.tenant_id, by_source.get(source_id, []))
        run = {
            "tenant_id": who.tenant_id,
            "id": new_id("run"),
            "source_id": source_id,
            "trigger": "full" if full else "retry" if retry else "manual",
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

    def _chunks(self, who: Who, item_id: str, version: int, title: str, result: Any) -> list[dict[str, Any]]:
        return [
            {
                "tenant_id": who.tenant_id,
                "id": new_id("chk"),
                "item_id": item_id,
                "version": version,
                "position": n,
                "title": title,
                "section": " > ".join(c.section_path),
                "page": c.page,
                "tokens": c.tokens,
                "text": c.text,
            }
            for n, c in enumerate(result.chunks)
        ]

    async def _reindex(
        self, who: Who, s: dict[str, Any], existing: dict[str, Any], *, name: str, mime: str, data: bytes
    ) -> dict[str, Any]:
        """The same content parsed and split again under its current version: no new version, no change row."""
        error: tuple[str, str] | None = None
        warning: str | None = None
        chunks: list[dict[str, Any]] = []
        title, pages = existing["title"], existing["page_count"]
        try:
            doc = parse(data, filename=name, mime_type=mime)
            title, pages = doc.title or name, doc.source.page_count
            chunks = self._chunks(who, existing["id"], existing["version"], title, split(doc, INGEST))
            if chunks:
                warning = _unread(doc.pages_without_text, doc.warnings)
            if not chunks and doc.pages_without_text:
                error = _no_text(f"{len(doc.pages_without_text)} pages have no text layer and OCR is not available.")
            elif not chunks:
                error = ("parse", "The document has no text to index.")
        except (UnsupportedFormatError, TooLargeError) as e:
            error = ("parse", str(e))
        except Exception as e:
            error = ("parse", f"The file could not be read: {type(e).__name__}.")
        values = {
            "title": title,
            "page_count": pages,
            "status": "failed" if error else "indexed",
            "error_class": error[0] if error else None,
            "error": error[1] if error else None,
            "warning": None if error else warning,
            "chunk_count": len(chunks),
            "processed_at": datetime.now(UTC),
        }
        await self.store.reindex(who.tenant_id, existing["id"], values, chunks)
        return {**existing, **values}

    async def _index(
        self,
        who: Who,
        s: dict[str, Any],
        existing: dict[str, Any] | None,
        *,
        file_id: str,
        name: str,
        mime: str,
        data: bytes,
        digest: str,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        item_id = existing["id"] if existing else new_id("itm")
        version = (existing["version"] + 1) if existing else 1
        chunks: list[dict[str, Any]] = []
        error: tuple[str, str] | None = None
        warning: str | None = None
        title, pages = name, None
        try:
            doc = parse(data, filename=name, mime_type=mime)
            title, pages = doc.title or name, doc.source.page_count
            result = split(doc, INGEST)
            for n, c in enumerate(result.chunks):
                chunks.append(
                    {
                        "tenant_id": who.tenant_id,
                        "id": new_id("chk"),
                        "item_id": item_id,
                        "version": version,
                        "position": n,
                        "title": title,
                        "section": " > ".join(c.section_path),
                        "page": c.page,
                        "tokens": c.tokens,
                        "text": c.text,
                    }
                )
            if chunks:
                warning = _unread(doc.pages_without_text, doc.warnings)
            if not chunks and doc.pages_without_text:
                error = _no_text(f"{len(doc.pages_without_text)} pages have no text layer and OCR is not available.")
            elif not chunks:
                error = ("parse", "The document has no text to index.")
        except (UnsupportedFormatError, TooLargeError) as e:
            error = ("parse", str(e))
        except Exception as e:
            error = ("parse", f"The file could not be read: {type(e).__name__}.")
        item = {
            "tenant_id": who.tenant_id,
            "id": item_id,
            "source_id": s["id"],
            "path": name,
            "title": title,
            "mime": mime,
            "size": len(data),
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
        }
        version_row = {
            "tenant_id": who.tenant_id,
            "item_id": item_id,
            "version": version,
            "file_id": file_id,
            "digest": digest,
            "status": "current",
            "created_by": who.email,
            "created_at": now,
        }
        change = None
        if existing is not None:
            before = await self.store.chunks(who.tenant_id, item_id)
            change = _change(who, s, item, existing["version"], before, chunks, now)
        await self.store.index_version(who.tenant_id, item, version_row, chunks, new=existing is None, change=change)
        return item

    # ── Retrieval ────────────────────────────────────────────────────────

    async def readable_bases(self, who: Who) -> list[dict[str, Any]]:
        """Every base of the tenant for a service, which checks its callers' grants itself; for a person, those of
        their team and those no team owns (c-222)."""
        if who.caller is not None and who.caller.kind == "service":
            return await self.store.bases(who.tenant_id)
        return await self.store.team_bases(who.tenant_id, who.team_id)

    async def search(self, who: Who, kb_ids: list[str], question: str, *, limit: int) -> list[dict[str, Any]]:
        """M1: passages for `question` across `kb_ids` in the caller's tenant, best first; empty when nothing passes
        the floor. Unknown ids are refused, never silently searched as empty, and a base a person may not read is
        unknown to them; a retired base is skipped, so an agent that still names it answers from its other bases."""
        tenant = who.tenant_id
        known = {b["id"] for b in await self.readable_bases(who)}
        retired = await self.store.retired(tenant, [k for k in kb_ids if k not in known])
        if missing := [k for k in kb_ids if k not in known and k not in retired]:
            raise NotFound(f"No knowledge base with id {missing[0]}.")
        live = [k for k in kb_ids if k in known]
        if not live:
            return []
        return [passage_out(p) for p in await self.retriever.search(tenant, live, question, limit=limit)]

    async def query(self, who: Who, kb_id: str, question: str) -> dict[str, Any]:
        """K12, as the console's playground reads it: the passages, cited, with the top one quoted as the answer
        (no model writes an answer in this slice)."""
        b = await self.store.base(who.tenant_id, kb_id)
        if b is None:
            raise NotFound("No knowledge base with that id.")
        if b["last_refreshed_at"] is None:
            raise Conflict("This knowledge base has not indexed anything yet; sync a source first.", code="not_indexed")
        started = datetime.now(UTC)
        limit = int(b["retrieval"].get("chunkLimit") or 8)
        passages = await self.retriever.search(who.tenant_id, [kb_id], question, limit=limit)
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
                    "chunkId": f"{p.item_id}:{n}",
                    "documentId": p.item_id,
                    "documentTitle": p.title,
                    "sourceName": source_name(p),
                    "score": p.score,
                    "location": _location(p.section, p.page),
                    "text": p.text,
                    "rejected": False,
                    "version": f"v{p.version}",
                }
                for n, p in enumerate(passages)
            ],
            **({"noAnswer": True} if not passages else {}),
            "retrievalMs": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "synthesisMs": 0,
            "shape": "chunks",
        }

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
        if values:
            await self.store.update_source(who.tenant_id, source_id, values)
        _, by_source = await self._joined(who.tenant_id)
        return self._source({**s, **values}, by_source.get(source_id, []))

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
                await self._sync(who, s, full=False, retry=retry)
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
            "status": i["status"],
            **({"errorClass": i["error_class"], "error": i["error"]} if i["error_class"] else {}),
            **({"warning": i["warning"]} if i.get("warning") else {}),
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
        """Files from Files added to the base (c-159): into its own documents source, made and attached the first
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

    async def item(self, who: Who, item_id: str) -> dict[str, Any]:
        found = await self.store.items(who.tenant_id, item_id=item_id)
        if not found:
            raise NotFound("No item with that id.")
        i = found[0]
        s = await self._source_row(who, i["source_id"])
        chunks = await self.store.chunks(who.tenant_id, item_id)
        versions = await self.store.versions(who.tenant_id, item_id)
        return {
            **self._item(i, s),
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
    }


def _unread(pages: list[int], warnings: list[str]) -> str | None:
    """What an indexed document left unread: its pages with no text layer, and a page limit it ran past."""
    said: list[str] = []
    if pages:
        listed = ", ".join(str(p) for p in pages[:10]) + (f" and {len(pages) - 10} more" if len(pages) > 10 else "")
        many = len(pages) > 1
        said.append(
            f"Page{'s' if many else ''} {listed} {'have' if many else 'has'} no text layer and OCR is not available, "
            f"so agents cannot cite {'them' if many else 'it'}."
        )
    said += [w for w in warnings if "no text layer" not in w]
    return " ".join(said) or None


class UnknownFile(ApiError):
    status = 404
    code = "file_not_found"


def source_team(s: dict[str, Any]) -> str:
    """The files-service team a source's files are stored under: the team that created the source."""
    return str(s["team_id"] or "team_ops")


def _location(section: str, page: int | None) -> str:
    return ", ".join(p for p in (f"p. {page}" if page else "", section) if p)


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
    }
