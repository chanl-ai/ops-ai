"""Knowledge bases and sources as the console reads them (apps/console/src/lib/types/knowledge.ts): rows with joined
names, details with attached sources, and lists paged and filtered on the server.

Fields this slice does not run yet (access settings, precedence, automation, schedules) are served with the values a
new knowledge base or source starts with, so the console's pages render without a mock;
docs/services/kb-service/overview.md gives the designed surface and says which part is built.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import dataclasses
import re
import time
from collections.abc import Coroutine, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict, cast

from pydantic import BaseModel, TypeAdapter, ValidationError

from ops_access import can, require_provisioner
from ops_documents_client import DocumentsRefused
from ops_identity import Principal, ServiceUnreachable
from ops_ingest import InvalidIngestError, ParsedDocument, SplitResult, split, validate_settings
from ops_ingest.metadata import Sensitivity, resolve_metadata
from ops_ingest.models import AI_STEPS, IngestApproval, IngestSettings, IngestStrategy
from ops_ingest.rules import ItemFacts, evaluate_rules
from ops_ingest.split import ai_step_allowed, document_digest
from ops_ingest.strategies.faq import piece_digest
from ops_ingest.text import approx_tokens
from ops_service_kit import narrow
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import Json, JsonValue, OptionsJSON, PageJSON, options_page, options_window
from ops_service_kit.ids import new_id
from ops_service_kit.listing import ListParams
from ops_service_kit.logging import get_logger
from ops_service_kit.names import slugify
from ops_service_kit.narrow import json_list, json_object
from ops_service_kit.settings import Settings
from ops_sources import find_places
from ops_store import documents, isolation
from ops_store.listing import ListPage
from ops_store.schedule import last_slot, next_run

from .agents import AgentDirectory, Usage
from .ai import AiClients, ai_run, spent_on
from .embedding import Embedder, EmbedFailed, embed_pending
from .files import FileIntake, FileMissing, FileNotScanned, Stored
from .origin import Origin, source_team
from .query_steps import (
    RERANK_POOL,
    REWRITE_MODES,
    QueryModel,
    QueryStepFailed,
    RerankTrace,
    RewriteTrace,
    ms_since,
    steps_for,
)
from .readings import READING_PENDING, ReadingAnswer, Readings, parsed_of, read_with
from .repeats import lines_of, repeated, without
from .retrieval import Found, Lane, Passage, Retriever, Scope, Search
from .schemas import (
    AccessSettings,
    AnswerSettings,
    IndexJob,
    ItemReading,
    PassageOut,
    PreviewIn,
    ReadingPage,
    RetrievalSettings,
    ScopesIn,
    ScopesPage,
    SearchOut,
    SourceDefaults,
    SourceHealth,
    SourcePreview,
    SyncSettings,
    Tombstone,
)
from .search import lanes_for
from .settled import Settled, parse_error, settled_new, settled_row
from .source_settings import (
    WEB_SCHEDULE,
    InvalidSettings,
    SourceSettings,
    defaults,
    index_key,
    merged,
    rebuild_for,
    split_settings,
    stored,
    wire,
)
from .store import DECIDABLE, KnowledgeStore
from .store.document_list import SHOWN_STATUS, doc_type, document_page
from .store.knowledge import (
    AuditEntry,
    BaseChanges,
    BaseRow,
    ChangeChanges,
    ChangeRow,
    ChangeWrite,
    ChunkRow,
    CopyName,
    DraftWrite,
    FaqUnitWrite,
    ItemChanges,
    ItemFetched,
    ItemRow,
    ItemWrite,
    NewBase,
    NewSource,
    PieceWrite,
    RunChanges,
    RunError,
    RunRow,
    RunWrite,
    SourceChanges,
    SourceRow,
    UnitWrite,
    VersionWrite,
)
from .store.vectors import PgVectorStore
from .tool_sources import (
    HOSTS,
    ToolReader,
    declared_source,
    declared_sources,
    preview_of,
    refusal_of,
    scopes_of,
    source_config,
    sync_tool_source,
    waiting_in,
)

# A new knowledge base's retrieval settings. searchMode, hybridWeight, chunkLimit and the thresholds decide every search
# of it (retrieval.py); rerank, rewrite and rewriteInstructions turn on the steps around it (query_steps.py), on the
# chat-model alias queryModel (empty: the environment's kb_query_alias); the scope and filter fields narrow which of
# its pieces a search may return. Keys a base stored before they were dropped (model, answerShape, ...) are ignored.
#
# The settings sections below are read from what a base stored, which a patch merged in unchecked before the sections
# were validated: a number may be stored as 8.0, "8" or true, so numbers are read with int()/float() where they are
# used, and a list, string or filter a read takes with `or` may be null.
type Number = int | float | str | bool


class Retrieval(TypedDict):
    """The retrieval settings a search reads (`search_settings`, `scope_of`): checked there, so a value nothing here
    reads, or reads through str()/bool(), may hold any JSON as it always could."""

    searchMode: JsonValue
    hybridWeight: Number
    rerank: JsonValue
    chunkLimit: Number
    threshold: Number
    meaningThreshold: Number
    rewrite: JsonValue
    rewriteInstructions: JsonValue
    queryModel: JsonValue
    # The scope lists and the filter are read with tuple() and dict() as they always were (`scope_of`), so any JSON a
    # base stored before saves were checked reads as it did: a string as its letters, [] as no filter.
    scopeCollections: JsonValue
    scopeSourceIds: JsonValue
    tagsInclude: JsonValue
    tagsExclude: JsonValue
    includeUntagged: JsonValue
    filters: JsonValue


class Answer(TypedDict):
    shape: str
    withholdUncited: bool
    noAnswerMessage: str


class Sync(TypedDict):
    changes: str
    removedAtSource: str
    staleAfterDays: Number
    notifyOnFailure: bool


class Mcp(TypedDict, total=False):
    enabled: bool
    toolName: str


class Access(TypedDict):
    mcp: Mcp


class SourceSplit(TypedDict):
    strategies: list[str]
    size: Number
    overlap: Number
    childSize: Number


class BaseSettings(TypedDict):
    """The sections a base keeps in its `settings` column."""

    answer: Answer
    sync: Sync
    access: Access
    sourceDefaults: SourceSplit


class Sections(BaseSettings):
    """Every settings section of a base as it applies: its retrieval column and its settings column. Retrieval stays
    JSON here: a reply or a save passes it on as stored, and only a search reads its keys (`Retrieval`)."""

    retrieval: Json


RETRIEVAL = documents.stored(Retrieval)
SECTIONS_READ = documents.stored(Sections)

DEFAULT_RETRIEVAL: Retrieval = {
    "searchMode": "hybrid",
    "hybridWeight": 0.6,
    "rerank": False,
    "chunkLimit": 8,
    "threshold": 0.5,
    "meaningThreshold": 0.38,
    "rewrite": "off",
    "rewriteInstructions": "",
    "queryModel": "",
    "scopeCollections": [],
    "scopeSourceIds": [],
    "tagsInclude": [],
    "tagsExclude": [],
    "includeUntagged": True,
    "filters": {"match": "all", "conditions": []},
}
NO_ANSWER = "I could not find that in the knowledge base."
# The base's other settings sections, kept in its `settings` column; `access.mcp.toolName` defaults to search_<slug>.
DEFAULT_SETTINGS: BaseSettings = {
    "answer": {"shape": "answer_with_citations", "withholdUncited": True, "noAnswerMessage": NO_ANSWER},
    "sync": {"changes": "apply", "removedAtSource": "remove", "staleAfterDays": 365, "notifyOnFailure": True},
    "access": {"mcp": {"enabled": False}},
    "sourceDefaults": {"strategies": ["structure", "context_headers"], "size": 400, "overlap": 40, "childSize": 120},
}
SECTIONS: dict[str, type[BaseModel]] = {
    "retrieval": RetrievalSettings,
    "answer": AnswerSettings,
    "sync": SyncSettings,
    "access": AccessSettings,
    "sourceDefaults": SourceDefaults,
}
# What each preset fills over the defaults; every value stays editable afterwards, and the base does not remember
# which preset it started from. `raw` is shown as "Search only": an agent or workflow answers from the pieces.
PRESETS: dict[str, dict[str, Json]] = {
    "balanced": {
        "retrieval": {"chunkLimit": 8, "threshold": 0.5, "meaningThreshold": 0.38},
        "answer": {"shape": "answer_with_citations", "withholdUncited": True},
    },
    "precise": {
        "retrieval": {"chunkLimit": 5, "threshold": 0.65, "meaningThreshold": 0.45},
        "answer": {"shape": "answer_with_citations", "withholdUncited": True},
    },
    "raw": {
        "retrieval": {"chunkLimit": 10, "threshold": 0.4, "meaningThreshold": 0.3},
        "answer": {"shape": "chunks", "withholdUncited": False},
    },
}
SOURCE_TYPES_IN_PHASE = ("file", "text", "push", "tool")
# Kinds whose items are written through the API (POST /v1/sources/{id}/items) and kept as files like uploads: typed
# text from the console's editor, and items another system pushes. A file source's items come from Files instead.
WRITTEN_TYPES = ("text", "push")
# The mime an item written as text is stored under unless the caller names another text type.
WRITTEN_TEXT_MIMES = {"text/markdown": ".md", "text/plain": ".txt", "text/html": ".html"}
SENSITIVITIES = ("internal", "confidential", "restricted")
MAX_PAGE_SIZE = 100
# A sync or rebuild holds its source's lease this long at a time and renews it every third of that while it runs, so
# a run that stops (its process gone) frees the source within LEASE, and a long one never loses it.
LEASE = timedelta(minutes=2)


@dataclass(frozen=True)
class Who:
    tenant_id: str
    email: str
    team_id: str | None
    # The verified caller, which `ops_access.can` decides on. None for the seed, which acts as the system.
    caller: Principal | None = None
    # A person's own identity headers, passed on when this service asks another on their behalf (a new source's
    # hosts, decided by the account's egress rule as theirs); empty for a service, the seed and the schedule.
    credentials: dict[str, str] = field(default_factory=dict[str, str])

    def require_builder(
        self, team_id: str | None, action: str, step: str = "edit", protection: str | None = None
    ) -> None:
        """`can(knowledge, step)` in the team that owns the record, or the team the request acts in for a create or
        a record no team owns: 403 `role_required` naming the area and action otherwise. Knowledge is shared by its
        team, so the grid gives every builder and admin of the team `knowledge.edit` on all of it."""
        if self.caller is None:
            return
        can(self.caller, "knowledge", step, team=team_id or self.team_id, what=f"to {action}", protection=protection)

    def require_provisioner_for(self, body: Provisioned | Mapping[str, JsonValue]) -> None:
        """Only the provisioning service sets `templateId` or `protection`; the seed, with no caller, may."""
        if self.caller is not None and (body.get("templateId") is not None or body.get("protection") is not None):
            require_provisioner(self.caller, "knowledge")


def _iso(v: datetime | None) -> str | None:
    return v.astimezone(UTC).isoformat() if v else None


def _slug(name: str) -> str:
    # Cut to the slug column (200) so a long name saves; the unbounded slug a name alone made was a 500.
    return slugify(name, width=200, sep="_")


def pagination(total: int, page: int, page_size: int) -> PageJSON:
    """The pagination block for `total` rows, `page` held to the pages there are (a store pages the same way)."""
    total_pages = max(1, -(-total // page_size))
    page = max(1, min(page, total_pages))
    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
        "hasNext": page < total_pages,
        "hasPrev": page > 1,
    }


# The Documents table's filters that are facets, by the row field each counts.
DOCUMENT_FACETS = ("sourceId", "status", "collection", "docType", "freshness", "sensitivity", "tags")
# The settings a source's patch may change, each validated and applied by its stage (source_settings.py).
SETTINGS_KEYS = ("parsing", "cleaning", "ingest", "rules", "metadataMapping", "schedule", "aiCeiling")
# The service event a source raises when it keeps failing, so a workflow can tell its owner.
FAILING_EVENT = "knowledge.source.failing"
FAILING_AFTER_RUNS = 2
FAILING_AFTER = timedelta(days=1)


# An item's status as the console names it: an item waiting for its file's reading is processing there.
# A file source's item when no documents-service is configured: kb-service reads no file itself.
NO_READER = ("parse", "Files are read by documents-service, which this installation does not run.")


def _no_text(error: str) -> tuple[str, str]:
    return "parse", f"no_text_layer: {error}"


def _used_by(using: dict[str, Usage] | None, kb_id: str) -> UsedBy:
    """The agents of the caller's team citing the base, how many of other teams do, and whether that is known."""
    if using is None:
        return {"agentNames": [], "agentsElsewhere": 0, "agentsKnown": False}
    u = using.get(kb_id) or Usage()
    return {"agentNames": u.names, "agentsElsewhere": u.elsewhere, "agentsKnown": True}


def item_total(counts: dict[str, int]) -> int:
    """Items in a source from its `item_counts`: the documents by status, which also carries `chunks` (their pieces,
    not items), so it is left out of the sum."""
    return sum(n for status, n in counts.items() if status != "chunks")


def _item_counts(s: SourceRow) -> ItemCounts:
    """What the source's documents are, from their items; an uploaded file not yet synced has no item and is pending.
    A source row built in memory (just created) has no documents yet."""
    counts: dict[str, int] = s.item_counts or {}
    synced = item_total(counts)
    return {
        "itemsIndexed": counts.get("indexed", 0),
        "itemsFailed": counts.get("failed", 0),
        "itemsPending": counts.get("pending", 0) + counts.get("reading", 0) + max(len(s.file_ids) - synced, 0),
    }


logger = get_logger(__name__)

# How far behind its schedule's latest slot a source may be and still be fresh: the beat that syncs it runs each minute.
# Capped at half the schedule's period, so an hourly source whose sync died reads stale before its next slot arrives.
FRESH_GRACE = timedelta(hours=1)


def _period(schedule: Json) -> timedelta:
    kind = schedule["kind"]
    if kind == "hourly":
        return timedelta(hours=int(cast(str | int, schedule["every"])))
    return timedelta(days=7) if kind == "weekly" else timedelta(days=1)


def freshness(schedule: Json, good: datetime | None, now: datetime) -> str:
    """`no_schedule` when the source only syncs when asked. Otherwise `stale` once its latest slot is more than the
    grace past and no good sync has happened since the slot (a failed run does not count, and a source that never
    synced well is stale); `fresh` before that, since the beat has until then to run the slot."""
    slot = last_slot(schedule, now)
    if slot is None:
        return "no_schedule"
    if good is not None and good >= slot:
        return "fresh"
    grace = min(FRESH_GRACE, _period(schedule) / 2)
    return "stale" if good is None or now > slot + grace else "fresh"


# The one precedence rule the index applies: a document a sync replaces keeps only its newest version in search.
PRECEDENCE = [
    {
        "id": "newer_version",
        "label": "A newer version of a document replaces the older one in search",
        "kind": "newer",
        "winner": "Newer version",
        "loser": "Older version",
    }
]


class Lease:
    """A source's sync lease held by one run: renewed every third of LEASE until released, so it outlives no stopped
    process and expires under no running one; released only by its own holder."""

    def __init__(self, store: KnowledgeStore, tenant: str, source_id: str, owner: str) -> None:
        self.store, self.tenant, self.source_id, self.owner = store, tenant, source_id, owner
        self.lost = False
        self._task = asyncio.create_task(self._keep())

    async def _keep(self) -> None:
        while True:
            await asyncio.sleep(LEASE.total_seconds() / 3)
            if not await self.store.renew(self.tenant, self.source_id, owner=self.owner, seconds=LEASE.total_seconds()):
                self.lost = True
                logger.warning("kb_lease_lost", source=self.source_id)
                return

    async def _stop(self) -> None:
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task

    async def release(self) -> None:
        await self._stop()
        await self.store.release(self.tenant, self.source_id, owner=self.owner)

    async def finish(self, run_id: str, values: RunChanges) -> None:
        """Writes the run's end and frees the source in one transaction: whoever sees it finished may sync at once."""
        await self._stop()
        await self.store.update_run(self.tenant, run_id, values, release=(self.source_id, self.owner))


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
        ai_clients: AiClients | None = None,
        query_model: QueryModel | None = None,
        query_alias: str = "default",
        search_wait_s: float | None = None,
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
        # Each run's model client for the sources' approved AI steps (ai.py); None in a stack with no models-service.
        self.ai_clients = ai_clients
        # Rerank and rewrite through models-service (query_steps.py); None in a stack with no models-service, where a
        # base asking for either is searched without it and the answer says why. `query_alias` is the environment's
        # chat-model alias for both, used by a base that names none.
        self.query_model = query_model
        self.query_alias = query_alias
        # The time a search's model steps (rewrite, the question's embedding, rerank) share, in sequence: a step
        # past it is skipped and says so, so a slow model never holds a caller past its own wait for this service.
        self.search_wait_s = Settings().kb_search_wait_s if search_wait_s is None else search_wait_s
        # Rebuilds running in this process, so stopping the service ends them and their runs say why.
        self.rebuilds: set[asyncio.Task[None]] = set()

    # ── Serialising ──────────────────────────────────────────────────────

    def settings_of(self, s: SourceRow) -> SourceSettings:
        """The source's saved settings over its kind's defaults; the environment's OCR mode is the default's. A plugin
        source whose items are a website's pages starts with a website's defaults."""
        return stored(kind_of(s), s.settings, ocr=self.ocr)

    def schedule_of(self, s: SourceRow) -> Json:
        """When the source syncs on its own: its saved schedule, else its plugin's for its kind of source, else a
        website's daily check, else manual."""
        saved = self.settings_of(s).schedule
        if saved is not None:
            return saved
        cfg: Json = dict(s.config or {})
        if kind_of(s) == "web":
            return WEB_SCHEDULE
        return json_object(cfg.get("schedule")) or {"kind": "manual"}

    def freshness_of(self, s: SourceRow, now: datetime | None = None) -> str:
        """`fresh`, `stale` or `no_schedule` for the source (see `freshness`). The clock is the database's, read with
        the source row, since the sync times it is compared with were written by that clock."""
        return freshness(self.schedule_of(s), s.last_good_sync_at, s.db_now or now or datetime.now(UTC))

    def review_state(self, s: SourceRow | None) -> ReviewState:
        """The Changes queue's freshness and review-by for a source's changes, from the same rule as its documents:
        review-by is the next scheduled sync, or the slot it missed when stale; blank with no schedule."""
        if s is None:
            return {"freshness": "no_schedule", "reviewBy": ""}
        now = s.db_now or datetime.now(UTC)
        state = self.freshness_of(s, now)
        schedule = self.schedule_of(s)
        when = last_slot(schedule, now) if state == "stale" else next_run(schedule, s.last_good_sync_at, now)
        return {"freshness": state, "reviewBy": _iso(when) or ""}

    def key_of(self, s: SourceRow) -> str:
        """The digest an item built now under the source's settings records (`indexed_with`)."""
        return index_key(self.settings_of(s), repeats_of(s))

    def _source(self, s: SourceRow, used_by: list[str]) -> SourceView:
        tool = s.type == "tool"
        cfg: Json = dict(s.config or {})
        applied = wire(self.settings_of(s))
        return {
            "id": s.id,
            "type": s.type,
            "name": s.name,
            # The kind its defaults and its label come from: file, web (a plugin source of one site's pages) or tool.
            "kind": kind_of(s),
            "kindLabel": kind_label(s),
            "scopeSummary": scope_summary(s),
            "config": (
                {
                    k: cfg.get(k)
                    for k in (
                        "plugin",
                        "source",
                        "title",
                        "listTool",
                        "getTool",
                        "connectionId",
                        "paused",
                        "site",
                        "values",
                    )
                }
                if tool
                else {"fileIds": s.file_ids}
            ),
            # Every stage's settings as a sync applies them.
            "parsing": applied["parsing"],
            "cleaning": applied["cleaning"],
            "ingest": applied["ingest"],
            "rules": applied["rules"],
            "metadataMapping": applied["metadataMapping"],
            "aiCeiling": applied["aiCeiling"],
            "aiStepsWaiting": ai_steps_waiting(self.settings_of(s).ingest),
            # Hosts of the source's own site an admin has yet to approve; nothing is fetched until they are.
            "waitingHosts": list(json_list(cfg.get("waitingHosts"))) if tool else [],
            "tags": s.tags,
            "titleFrom": "heading",
            "permissions": {"mode": "workspace"},
            "schedule": (schedule := self.schedule_of(s)),
            **(
                SourceParts(nextSyncAt=_iso(n))
                if s.status == "active" and (n := next_run(schedule, s.last_sync_at, datetime.now(UTC)))
                else SourceParts()
            ),
            "health": health_of(s).model_dump(by_alias=True, exclude_unset=True),
            "deletedAtSource": "remove",
            "staleAfterDays": 365,
            "notifyOnFailure": True,
            "sensitivity": s.sensitivity,
            "collection": s.collection,
            "owner": s.owner,
            "status": s.status,
            **_item_counts(s),
            **(SourceParts(lastSyncAt=_iso(s.last_sync_at)) if s.last_sync_at else SourceParts()),
            **(SourceParts(lastRunStatus=s.last_run_status) if s.last_run_status else SourceParts()),
            "usedByKbIds": used_by,
            "createdAt": _iso(s.created_at),
        }

    async def _counts(self, tenant: str) -> dict[str, SourceCounts]:
        """Each source's documents by status and its indexed chunks, from its items, and when it last synced."""
        rows = await self.store.sources(tenant)
        return {str(x.id): self._count_of(x) for x in rows}

    def _count_of(self, s: SourceRow) -> SourceCounts:
        """What a base's reply reads of the source (`_base`), from its `item_counts`; a status it holds none of is 0."""
        n = s.item_counts
        return {
            "indexed": n.get("indexed", 0),
            "failed": n.get("failed", 0),
            "chunks": n.get("chunks", 0),
            "synced": s.last_sync_at,
            "freshness": self.freshness_of(s),
        }

    async def _jobs(self, tenant: str, source_ids: list[str]) -> list[IndexJob]:
        """A knowledge base's recent index jobs: the newest runs of the sources it reads, as the Overview lists them."""
        runs = await self.store.runs(tenant, source_ids=source_ids, limit=10)
        return [
            IndexJob(
                id=r.id,
                started_at=r.started_at.astimezone(UTC).isoformat(),
                duration_sec=r.duration_sec,
                processed=r.counts.get("upserted", 0),
                failed=r.counts.get("failed", 0),
                status=r.status,
                trigger=r.trigger,
            )
            for r in runs
        ]

    def _base(
        self,
        b: BaseRow,
        source_ids: list[str],
        counts: dict[str, SourceCounts],
        jobs: list[IndexJob] | None = None,
    ) -> BaseView:
        mine = [counts.get(sid, SourceCounts()) for sid in source_ids]
        # When the base was last read: its newest source sync, the same time each source row shows. Content changing
        # (lastRefreshedAt) is a separate fact, and a sync that changes nothing does not move it.
        synced = max((t for c in mine if (t := c.get("synced"))), default=None)
        documents = sum(c.get("indexed", 0) for c in mine)
        failures = sum(c.get("failed", 0) for c in mine)
        if b.last_refreshed_at is None:
            health, reasons = "never", ["Never indexed"]
        elif failures:
            health, reasons = "degraded", [f"{failures} document{'s' if failures != 1 else ''} failed to index"]
        else:
            health, reasons = "healthy", []
        settings = settings_of(b)
        return {
            "id": b.id,
            "name": b.name,
            "slug": b.slug,
            "templateId": b.template_id,
            "protection": b.protection,
            "description": b.description,
            "color": b.color,
            "owner": b.owner,
            "sources": [
                {"sourceId": s, "itemsContributed": counts.get(s, {}).get("indexed", 0), "rules": []}
                for s in source_ids
            ],
            "collections": b.collections,
            "precedence": PRECEDENCE,
            "metadataProfile": {"required": []},
            # The sections in the order `sections_of` builds them, access last, with the reply's own keys.
            "retrieval": settings["retrieval"],
            "answer": settings["answer"],
            "sync": settings["sync"],
            "sourceDefaults": settings["sourceDefaults"],
            "access": {
                # Every base is searchable by its whole team; no narrower list is kept.
                "members": {"mode": "all", "principals": []},
                "anyApiKey": False,
                "mcp": settings["access"]["mcp"],
                "publicLink": {
                    "enabled": False,
                    "slug": b.slug.replace("_", "-"),
                    "answerStyle": "chat",
                    "rateLimit": 300,
                    "showSourceLinks": True,
                },
                "documentPermissions": "workspace",
            },
            "automation": "suggest" if settings["sync"]["changes"] == "review" else "act",
            # Queries are not logged yet, so their counts are 0 and the console does not show them.
            "stats": {
                "documents": documents,
                "chunks": sum(c.get("chunks", 0) for c in mine),
                "failures": failures,
                "stale": sum(c.get("indexed", 0) for c in mine if c.get("freshness") == "stale"),
                "queries7d": 0,
                "queriesChange7d": 0,
                "noAnswerRate": 0,
                "medianLatencyMs": 0,
            },
            "health": health,
            "healthReasons": reasons,
            **(BaseParts(lastRefreshedAt=_iso(b.last_refreshed_at)) if b.last_refreshed_at else BaseParts()),
            **(BaseParts(lastSyncAt=_iso(synced)) if synced else BaseParts()),
            "jobs": [j.model_dump(by_alias=True) for j in jobs or []],
            "createdAt": _iso(b.created_at),
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
    ) -> OptionsJSON[dict[str, str | None]]:
        """The agent page's knowledge picker: each base as an option storing its id, labelled by name, with its
        owner as the hint. `ids` resolves stored values to labels; one not found is left out."""
        offset, window = options_window(None if ids else cursor, limit)
        rows = await self.store.base_options(
            who.tenant_id, who.team_id, search=search, offset=offset, limit=window, ids=ids
        )
        options = [{"id": r.id, "label": r.name, "hint": r.owner or None, "disabled": None} for r in rows]
        return options_page(options, offset, limit)

    async def list_bases(self, who: Who, q: ListParams) -> ListPage:
        """A page of the team's bases, paged and counted in SQL with no other service asked; then, with no
        transaction open, agents-service's "used by" for the page's bases."""
        found = await self.store.base_page(who.tenant_id, q)
        if not found.bases:
            return found.page
        using = await self.agents.usage(who.tenant_id, who.team_id, [b.id for b in found.bases])
        counts = {s.id: self._count_of(s) for s in found.sources}
        names = {s.id: s.name for s in found.sources}
        found.page["data"] = [
            {
                **self._base(b, found.links.get(b.id, []), counts),
                "sourceNames": [names[s] for s in found.links.get(b.id, []) if s in names],
                **_used_by(using, b.id),
            }
            for b in found.bases
        ]
        return found.page

    async def get_base(self, who: Who, kb_id: str) -> BaseDetailView:
        """The base with its sources, counts, jobs and coverage read in one transaction; then, with none open,
        agents-service's "used by"."""
        async with isolation.request_transaction():
            b = await self.store.base(who.tenant_id, kb_id)
            if b is None:
                raise NotFound("No knowledge base with that id.")
            by_kb, by_source = await self._joined(who.tenant_id)
            attached = await self.store.sources(who.tenant_id, by_kb.get(kb_id, []))
            running = await self.store.running_sources(who.tenant_id)
            counts = await self._counts(who.tenant_id)
            jobs = await self._jobs(who.tenant_id, by_kb.get(kb_id, []))
            cov = await self.embedding_coverage(who, kb_id)
        using = await self.agents.usage(who.tenant_id, who.team_id, [kb_id])
        return {
            **self._base(b, by_kb.get(kb_id, []), counts, jobs),
            "sourceNames": [s.name for s in attached],
            **_used_by(using, kb_id),
            "attached": [
                {
                    "sourceId": s.id,
                    "itemsContributed": s.item_counts.get("indexed", 0),
                    "rules": [],
                    "source": self._source(s, by_source.get(s.id, [])),
                    # A sync or rebuild holds it now, so the base's Sources tab polls while it runs.
                    "running": s.id in running,
                }
                for s in attached
            ],
            "metadataKeys": [],
            "suggestedQuestions": [],
            "heldCount": 0,
            **(DetailParts(embedding=cov) if cov else DetailParts()),
            **self._rights(who, b.team_id, b.name, b.protection),
        }

    async def create_base(self, who: Who, i: BaseInput) -> BaseView:
        who.require_builder(who.team_id, "create a knowledge base", "create")
        if who.team_id is None:
            raise ValidationFailed("A knowledge base is made in one team; this call names none.", code="team_required")
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
        if any(b.name.lower() == name.lower() for b in existing):
            raise Conflict("A knowledge base with this name already exists.")
        if (kb_id := i.get("id")) and any(b.id == kb_id for b in existing):
            raise Conflict(f"A knowledge base with id {kb_id} already exists.")
        who.require_provisioner_for(i)
        source_ids = list(dict.fromkeys(i.get("sourceIds") or []))
        await self._known_sources(who, source_ids)
        preset = PRESETS.get(str(i.get("preset") or "balanced"), PRESETS["balanced"])
        slug = _slug(name)
        defaults = narrow.an_object(sections_of(slug, {}, None), "settings")
        start = SECTIONS_READ({k: {**narrow.an_object(v, k), **preset.get(k, {})} for k, v in defaults.items()})
        chosen = settled(start, {k: i.get(k) for k in SECTIONS})
        row: NewBase = {
            "tenant_id": who.tenant_id,
            "id": i.get("id") or new_id("kb"),
            "team_id": who.team_id,
            "name": name,
            "slug": slug,
            "description": str(i.get("description") or ""),
            "color": str(i.get("color") or "blue"),
            "owner": owner,
            "collections": list(i.get("collections") or []),
            "retrieval": narrow.an_object(chosen["retrieval"], "retrieval"),
            "settings": {k: v for k, v in narrow.an_object(chosen, "settings").items() if k != "retrieval"},
            "created_by": who.email,
            "created_at": datetime.now(UTC),
            "last_refreshed_at": None,
            "template_id": i.get("templateId"),
            "protection": i.get("protection"),
        }
        await self.store.create_base(row, source_ids)
        made = BaseRow.model_validate(
            {k: v for k, v in row.items() if k != "tenant_id"} | {"documents_source_id": None, "revision": 0}
        )
        return self._base(made, source_ids, await self._counts(who.tenant_id))

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

    def _rights(self, who: Who, team_id: str | None, what: str, protection: str | None) -> Rights:
        """`canEdit`, `canDelete` and `canPublish` for a detail response, from the check the write routes run,
        so the console never disagrees with them. Knowledge is changed in place, never published."""

        def may(step: str) -> bool:
            try:
                self._may_change(who, team_id, what, step, protection=protection)
            except Forbidden:
                return False
            return True

        return {"canPublish": False, "canEdit": may("edit"), "canDelete": may("delete")}

    async def _changeable(self, who: Who, kb_id: str, step: str = "edit") -> BaseRow:
        """The knowledge base, when the caller may change it (`_may_change`)."""
        b = await self.store.base(who.tenant_id, kb_id)
        if b is None:
            raise NotFound("No knowledge base with that id.")
        self._may_change(who, b.team_id, b.name, step, protection=b.protection)
        return b

    async def update_base(self, who: Who, kb_id: str, patch: dict[str, Any]) -> BaseView:
        b = await self._changeable(who, kb_id)
        who.require_provisioner_for(patch)
        values: BaseChanges = {}
        if patch.get("templateId"):
            values["template_id"] = patch["templateId"]
        if patch.get("protection"):
            values["protection"] = patch["protection"]
        if patch.get("name") is not None:
            name = str(patch["name"]).strip()
            if not name:
                raise ValidationFailed("Give the knowledge base a name.")
            taken = any(x.id != kb_id for x in await self.store.taken(who.tenant_id, name=name))
            if taken:
                raise Conflict("A knowledge base with this name already exists.")
            values["name"] = name
            values["slug"] = _slug(name)
        if patch.get("owner") is not None:
            if not str(patch["owner"]).strip():
                raise ValidationFailed("A knowledge base always has an owner.", code="collection_without_owner")
            values["owner"] = str(patch["owner"]).strip()
        if patch.get("description") is not None:
            values["description"] = patch["description"]
        if patch.get("color") is not None:
            values["color"] = patch["color"]
        if patch.get("collections") is not None:
            values["collections"] = patch["collections"]
        # The route dumps the patch by field name, so the source defaults arrive as source_defaults.
        sections = {k: patch.get(k, patch.get(re.sub(r"([A-Z])", r"_\1", k).lower())) for k in SECTIONS}
        if any(v is not None for v in sections.values()):
            current = settings_of(b)
            after = settled(current, sections)
            if after["retrieval"] != dict(b.retrieval):
                values["retrieval"] = narrow.an_object(after["retrieval"], "retrieval")
            rest = {k: v for k, v in narrow.an_object(after, "settings").items() if k != "retrieval"}
            if rest != dict(b.settings or {}):
                values["settings"] = rest
        if values:
            entry = audit_entry(who, "knowledge.base.settings", "knowledge_base", kb_id, b.name, b.model_dump(), values)
            await self.store.update_base(who.tenant_id, kb_id, values, audit=entry)
        by_kb, _ = await self._joined(who.tenant_id)
        return self._base(b.model_copy(update=values), by_kb.get(kb_id, []), await self._counts(who.tenant_id))

    async def attach(self, who: Who, kb_id: str, source_ids: list[str]) -> BaseView:
        b = await self._changeable(who, kb_id)
        await self._known_sources(who, source_ids)
        await self.store.attach(who.tenant_id, kb_id, source_ids)
        by_kb, _ = await self._joined(who.tenant_id)
        return self._base(b, by_kb.get(kb_id, []), await self._counts(who.tenant_id))

    async def remove_base(self, who: Who, kb_id: str) -> None:
        await self._changeable(who, kb_id, "delete")
        if not await self.store.remove_base(who.tenant_id, kb_id, by=who.email):
            raise NotFound("No knowledge base with that id.")

    async def _base_split(self, tenant: str, kb_id: str) -> Json:
        """The splitting values a base's source defaults set apart from the defaults: what a new source copies."""
        b = await self.store.base(tenant, kb_id)
        if b is None:
            return {}
        default = narrow.an_object(DEFAULT_SETTINGS["sourceDefaults"], "sourceDefaults")
        split = narrow.an_object(settings_of(b)["sourceDefaults"], "sourceDefaults")
        return {k: v for k, v in split.items() if default.get(k) != v}

    async def sync_rules(self, tenant: str, source_id: str) -> Sync:
        """How syncs of a source treat what they find, from the bases it feeds: when they differ the strictest wins
        (review over apply, keep over remove, the fewest days to stale, notify when any base asks)."""
        by_kb, _ = await self._joined(tenant)
        bases = {b.id: b for b in await self.store.bases(tenant)}
        rules = [settings_of(bases[k])["sync"] for k, srcs in by_kb.items() if source_id in srcs and k in bases]
        if not rules:
            return {**DEFAULT_SETTINGS["sync"]}
        return {
            "changes": "review" if any(r["changes"] == "review" for r in rules) else "apply",
            "removedAtSource": "keep" if any(r["removedAtSource"] == "keep" for r in rules) else "remove",
            "staleAfterDays": min(int(r["staleAfterDays"]) for r in rules),
            "notifyOnFailure": any(bool(r["notifyOnFailure"]) for r in rules),
        }

    async def _known_sources(self, who: Who, source_ids: list[str]) -> None:
        found = {s.id for s in await self.store.sources(who.tenant_id, source_ids)}
        if missing := [s for s in source_ids if s not in found]:
            raise NotFound(f"No source with id {missing[0]}.")

    # ── Sources ──────────────────────────────────────────────────────────

    async def list_sources(self, who: Who, q: ListParams) -> ListPage:
        found = await self.store.source_page(who.tenant_id, q)
        found.page["data"] = [
            {
                **self._source(s, [b.id for b in found.feeds.get(s.id, [])]),
                "usedBy": [b.model_dump() for b in found.feeds.get(s.id, [])],
                "running": s.id in found.running,
            }
            for s in found.sources
        ]
        return found.page

    async def plugin_sources(self, who: Who, plugin: str) -> list[PluginSourceView]:
        """The sources the caller's team made from one plugin's knowledge sources, each with the bases it feeds. Read
        by the team the call names, a service's included, so an app's resource list shows only that team's."""
        if not who.team_id:
            raise ValidationFailed(
                "Plugin sources are listed for one team; this call names none.", code="team_required"
            )
        _, by_source = await self._joined(who.tenant_id)
        return [
            {
                "id": s.id,
                "name": s.name,
                "source": str(cfg.get("source") or ""),
                "kbIds": by_source.get(s.id, []),
            }
            for s in await self.store.sources(who.tenant_id)
            if s.type == "tool" and s.team_id == who.team_id and (cfg := dict(s.config or {})).get("plugin") == plugin
        ]

    async def get_source(self, who: Who, source_id: str) -> SourceDetailView:
        found = await self.store.sources(who.tenant_id, [source_id])
        if not found:
            raise NotFound("No source with that id.")
        s = found[0]
        _, by_source = await self._joined(who.tenant_id)
        readers = [b for b in await self.store.bases(who.tenant_id) if b.id in by_source.get(source_id, [])]
        recent = [_run(r) for r in (await self.store.runs(who.tenant_id, source_id=source_id))[:5]]
        items = await self.store.items(who.tenant_id, source_ids=[source_id])
        rules = await self.sync_rules(who.tenant_id, source_id)
        return {
            **self._source(s, by_source.get(source_id, [])),
            # What its syncs apply, from the bases it feeds (the strictest wins).
            "deletedAtSource": rules["removedAtSource"],
            "staleAfterDays": rules["staleAfterDays"],
            "notifyOnFailure": rules["notifyOnFailure"],
            "readers": [
                {
                    "id": b.id,
                    "name": b.name,
                    "slug": b.slug,
                    "color": b.color,
                    # The base's health as judged without its sources (never refreshed or not), so no counts read.
                    "health": self._base(b, [], {})["health"],
                }
                for b in readers
            ],
            "recentRuns": recent,
            "running": next((r for r in recent if r["status"] == "running"), None),
            **self._rights(who, s.team_id, s.name, None),
            # The Last sync tile's "Took ..." hint; absent until a first run.
            **cast(LastRun, {"lastRunDurationSec": recent[0]["durationSec"]} if recent else {}),
            "errorGroups": [],
            "itemCount": item_total(s.item_counts),
            "reindexNeeded": any(self.built_under_other_settings(s, i) for i in items),
            "requiredMetadata": [],
            "governance": {
                "excluded": 0,
                "held": 0,
                "duplicates": sum(1 for i in items if i.duplicate_of or i.status == "skipped"),
                "superseded": 0,
            },
        }

    async def create_source(self, who: Who, i: SourceInput) -> SourceView:
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
        if who.team_id is None:
            raise ValidationFailed("A source is made in one team; this call names none.", code="team_required")
        now = datetime.now(UTC)
        row = SourceRow(
            id=new_id("src"),
            team_id=who.team_id,
            type=kind,
            name=name,
            collection=str(i.get("collection") or ""),
            owner=str(i.get("owner") or who.email),
            sensitivity=sensitivity,
            status="draft" if i.get("status") == "draft" else "active",
            tags=list(i.get("tags") or []),
            file_ids=[],
            file_names=None,
            created_by=who.email,
            created_at=now,
            last_sync_at=None,
            last_run_status=None,
            # Read through a connection's tools: what tools-service declares for the team, checked now.
            config=await source_config(self.tools, who, i.get("config") or {}) if kind == "tool" else None,
            lease_until=None,
            lease_owner=None,
            settings=None,
            last_good_sync_at=None,
            failing_since=None,
            failures_in_row=0,
            db_now=now,
            item_counts={},
        )
        given = {k: v for k in SETTINGS_KEYS if (v := i.get(k)) is not None}
        if kb_ids and (split := await self._base_split(who.tenant_id, kb_ids[0])):
            # A new source of a base splits as the base says, where it says something other than the default; the
            # source keeps its own copy, and what the create sends wins.
            given["ingest"] = {**split, **dict(given.get("ingest") or {})}
        row = row.model_copy(update={"settings": wire(self._merged(self.settings_of(row), given)) if given else None})
        # Files named at creation are checked and referenced like any added later, before the source exists.
        names = [await self._use_file(who, row, f) for f in dict.fromkeys(i.get("fileIds") or [])]
        row = row.model_copy(update={"file_ids": [f for f, _ in names], "file_names": dict(names)})
        await self.store.create_source(new_source(row, who.tenant_id), kb_ids)
        if i.get("sync"):
            # Add source's Create and sync: the first run starts now, in the background, and shows on the source.
            self._in_background(self._first_sync(who, row))
        return self._source(row, kb_ids)

    def _in_background(self, work: Coroutine[Any, Any, Any]) -> None:
        """Work that outlives the request, ended when the service stops (as a rebuild is)."""
        task = asyncio.create_task(work)
        self.rebuilds.add(task)
        task.add_done_callback(self.rebuilds.discard)

    async def _first_sync(self, who: Who, s: SourceRow) -> None:
        try:
            if s.type == "tool":
                await self.sync_tool(who, s, full=False, trigger="manual")
            else:
                await self._held_sync(who, s, full=False, retry=False)
        except ApiError as e:
            # A sync that could not start (the lease is held, the plugin turned off) is recorded on its source.
            logger.info("kb_first_sync_not_started", source=s.id, code=e.code)

    async def source_kinds(self, who: Who) -> list[SourceKindView]:
        """Files, then each knowledge source the team's apps offer (none when this service reads no tools)."""
        out: list[SourceKindView] = [
            {"type": t, "kind": t, "group": "built_in", "title": KIND_LABEL[t], **kind_defaults(t, self.ocr)}
            for t in ("file", *WRITTEN_TYPES)
        ]
        if self.tools is None or not who.team_id:
            return out
        for d in await declared_sources(self.tools, who.tenant_id, str(who.team_id)):
            needs = d.needsConnection
            refusal = refusal_of(d)
            out.append(
                {
                    "type": "tool",
                    "group": "apps",
                    "title": d.title,
                    "plugin": d.plugin,
                    "source": d.source,
                    "site": d.site,
                    "files": d.files,
                    "connectionId": d.connectionId,
                    "needsConnection": needs,
                    "connected": not needs or (bool(d.connectionId) and d.connectionStatus == "healthy"),
                    "canCreate": refusal is None,
                    **cast(
                        AppKindParts,
                        {"cannotCreateCode": refusal[0], "cannotCreateBecause": refusal[1]} if refusal else {},
                    ),
                    "previews": bool(d.previewTool),
                    "pickers": bool(d.scopesTool),
                    "inputs": d.inputs,
                    # What a new source of this kind starts with, so Add source's Review shows the defaults it applies.
                    "kind": (kind := "web" if d.site else "tool"),
                    **kind_defaults(kind, self.ocr, plugin_schedule=d.schedule),
                }
            )
        return out

    async def preview_source(self, who: Who, i: PreviewIn) -> SourcePreview:
        """A plugin source's preview before it is made: its settings checked as a create checks them, then the
        plugin's preview tool asked what they would take in."""
        who.require_builder(who.team_id, "preview a source", "create")
        cfg = await source_config(self.tools, who, i.config)
        tool = cfg.get("previewTool")
        if not tool or self.tools is None:
            raise ValidationFailed("This kind of source has no preview.", code="preview_unavailable")
        if waiting := waiting_in(cfg):
            # The preview fetches from the site too, so it waits for the same approval a sync does.
            raise Conflict(
                f"Waiting for an admin to approve {waiting[0]}. The source can be added now; it syncs once approved.",
                code="host_waiting",
            )
        given: dict[str, JsonValue] = {"source": cfg["values"]} if cfg.get("values") else {}
        answer = await self.tools.call(who.tenant_id, str(who.team_id), str(tool), given, act="kb-preview")
        if not answer.ok:
            # The plugin or the site failed, not this request: said as the store being unavailable, with its reason.
            raise ServiceUnavailable(
                f"The preview could not run: {answer.message or answer.code}", code="preview_failed"
            )
        return preview_of(answer.output)

    async def source_scopes(self, who: Who, i: ScopesIn) -> ScopesPage:
        """A plugin source's pickers: its scopes tool asked, as the team's connection, for what matches `query` (or
        what `parent` holds). Refused for a kind of source that has no pickers."""
        who.require_builder(who.team_id, "pick what a source takes in", "create")
        found = await declared_source(self.tools, who, i.plugin, i.source)
        if self.tools is None:
            raise ValidationFailed(f"{found.title} has nothing to pick.", code="scopes_unavailable")
        places, following = await find_places(
            self.tools, who.tenant_id, str(who.team_id), found, query=i.query, parent=i.parent, cursor=i.cursor,
            act="kb-scopes",
        )  # fmt: skip
        return scopes_of(places, following)

    async def remove_source(self, who: Who, source_id: str) -> None:
        await self._changeable_source(who, source_id, "delete")
        if not await self.store.remove_source(who.tenant_id, source_id):
            raise NotFound("No source with that id.")

    # ── Files and sync ───────────────────────────────────────────────────

    async def _source_row(self, who: Who, source_id: str) -> SourceRow:
        found = await self.store.sources(who.tenant_id, [source_id])
        if not found:
            raise NotFound("No source with that id.")
        return found[0]

    async def _changeable_source(self, who: Who, source_id: str, step: str = "edit") -> SourceRow:
        """The source, when the caller may change what it holds (`_may_change`)."""
        s = await self._source_row(who, source_id)
        self._may_change(who, s.team_id, s.name, step)
        return s

    async def upload(self, who: Who, source_id: str, data: bytes, *, name: str, mime: str) -> Uploaded:
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

    async def _use_file(self, who: Who, s: SourceRow, file_id: str) -> tuple[str, str]:
        try:
            name = await self.files.use(who.tenant_id, source_team(s), file_id, source_id=s.id, source_name=s.name)
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
        held = set(s.file_ids)
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

    async def sync(self, who: Who, source_id: str, *, full: bool = False, retry: bool = False) -> RunView:
        s = await self._changeable_source(who, source_id)
        if s.type == "tool":
            return await self.sync_tool(who, s, full=full, trigger="full" if full else "manual")
        return await self._held_sync(who, s, full=full, retry=retry)

    async def scheduled_sync(self, who: Who, s: SourceRow) -> RunView:
        """A sync the schedule starts, of either kind, recorded with trigger `schedule`."""
        if s.type == "tool":
            return await self.sync_tool(who, s, full=False, trigger="schedule")
        return await self._held_sync(who, s, full=False, retry=False, trigger="schedule")

    async def take_lease(self, tenant: str, source_id: str) -> Lease | None:
        """The source's lease, renewed in the background until released; None when another run holds it."""
        owner = new_id("lease")
        if not await self.store.claim(tenant, source_id, owner=owner, seconds=LEASE.total_seconds()):
            return None
        return Lease(self.store, tenant, source_id, owner)

    async def _held_sync(
        self,
        who: Who,
        s: SourceRow,
        *,
        full: bool,
        retry: bool,
        trigger: str | None = None,
        only: str | None = None,
    ) -> RunView:
        """A file source's sync under its lease, so a rebuild, the schedule and a manual sync never run it at once.
        `only` names the one item to read (an item just written), so a write costs one file, not the whole source."""
        source_id = str(s.id)
        lease = await self.take_lease(who.tenant_id, source_id)
        if lease is None:
            raise Conflict(f"{s.name} is syncing or rebuilding now; wait for that run to end.", code="sync_running")
        try:
            with ai_run(self.ai_clients, who.tenant_id, ceiling=self.settings_of(s).ai_ceiling):
                return await self._sync(who, s, full=full, retry=retry, trigger=trigger, only=only)
        finally:
            await lease.release()

    async def hosts_approved(self, who: Who, s: SourceRow) -> SourceRow:
        """The source once every host it waits on is approved, read again from tools-service as this service: 409
        `host_waiting` naming the first host still waiting, so nothing is fetched from a site no admin approved."""
        cfg = dict(s.config or {})
        waiting = waiting_in(cfg)
        if not waiting or self.tools is None:
            return s
        answers = HOSTS.validate_python(await self.tools.source_hosts(who.tenant_id, str(s.team_id), cfg))
        still = [h for h in waiting if any(a.host == h and a.state != "allowed" for a in answers)]
        if still:
            raise Conflict(f"Waiting for an admin to approve {still[0]}.", code="host_waiting")
        cfg["waitingHosts"] = []
        await self.store.update_source(who.tenant_id, str(s.id), {"config": cfg})
        return s.model_copy(update={"config": cfg})

    async def sync_tool(self, who: Who, s: SourceRow, *, full: bool, trigger: str) -> RunView:
        """A tool source's sync under its lease, so a manual sync and the schedule never run it at once."""
        if self.tools is None:
            raise Conflict("This service reads no tools, so the source cannot sync.", code="tools_unavailable")
        if s.status == "paused":
            raise Conflict(f"{s.name} is paused; resume it to sync.", code="source_paused")
        s = await self.hosts_approved(who, s)
        lease = await self.take_lease(who.tenant_id, str(s.id))
        if lease is None:
            raise Conflict(f"{s.name} is syncing now; wait for that run to end.", code="sync_running")
        try:
            with ai_run(self.ai_clients, who.tenant_id, ceiling=self.settings_of(s).ai_ceiling):
                run = _run(run_row(await sync_tool_source(self, self.tools, who, s, full=full, trigger=trigger)))
        finally:
            await lease.release()
        await self.settle_repeats(who, str(s.id))
        return run

    async def settle_repeats(self, who: Who, source_id: str) -> None:
        """Counts the lines repeated across a website source's pages after a sync; when the set changed, the pages
        built under the old set are rebuilt in the background from their snapshots, with nothing fetched."""
        s = await self._source_row(who, source_id)
        if not self.settings_of(s).cleaning.site_repeats:
            return
        items = [i for i in await self.store.items(who.tenant_id, source_ids=[source_id]) if i.status == "indexed"]
        found = repeated([str(x) for x in i.lines] if i.lines is not None else None for i in items)
        cfg: Json = dict(s.config or {})
        if found == list(json_list(cfg.get("repeats"))):
            return
        cfg["repeats"] = [*found]
        await self.store.update_source(who.tenant_id, source_id, {"config": cfg})
        await self.start_rebuild(who, s.model_copy(update={"config": cfg}))

    async def settle_run(self, who: Who, s: SourceRow, status: str, *, activate: bool) -> None:
        """Records a run's outcome on the source; the second failure in a row, or a failure a day into a failing
        streak, raises the failing event once, with the source and its last error."""
        before = s.failing_since
        in_row = await self.store.mark_synced(who.tenant_id, str(s.id), status, activate=activate)
        if status != "failed":
            await self.embed_now(who.tenant_id)
            return
        long_failing = isinstance(before, datetime) and datetime.now(UTC) - before >= FAILING_AFTER
        if not (await self.sync_rules(who.tenant_id, str(s.id)))["notifyOnFailure"]:
            # Every base the source feeds turned the alert off; the run is still recorded as failed.
            return
        if in_row == FAILING_AFTER_RUNS or (long_failing and in_row > FAILING_AFTER_RUNS and in_row % 24 == 0):
            payload: dict[str, JsonValue] = {
                "sourceId": s.id,
                "sourceName": s.name,
                "owner": s.owner,
                "failedRuns": in_row,
                "failingSince": _iso(before) if isinstance(before, datetime) else None,
            }
            await self.store.record_event(who.tenant_id, str(s.id), name=FAILING_EVENT, payload=payload)

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

    async def start_rebuild(self, who: Who, s: SourceRow) -> RunView | None:
        """Rebuilds, in the background, every item of the source built under other settings: split again from its
        stored reading, or read again when the OCR mode changed. Nothing is fetched from where the item came from. The
        run holds the source's lease, so no sync runs beside it, and stops between two items when cancelled. None when
        no item needs it, or a sync holds the source now (that sync, or the next, rebuilds them)."""
        tenant, source_id = who.tenant_id, str(s.id)
        stale = [
            i for i in await self.store.items(tenant, source_ids=[source_id]) if self.built_under_other_settings(s, i)
        ]
        lease = await self.take_lease(tenant, source_id) if stale else None
        if lease is None:
            return None
        run: RunWrite = {
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
        self._in_background(self._rebuild(who, s, run, stale, lease))
        return _run(run_row(run))

    async def _rebuild(self, who: Who, s: SourceRow, run: RunWrite, stale: list[ItemRow], lease: Lease) -> None:
        # A run of its own for the AI steps: its task may be made inside a sync, whose run it must not share.
        try:
            with ai_run(self.ai_clients, who.tenant_id, ceiling=self.settings_of(s).ai_ceiling, fresh=True):
                await self._rebuild_items(who, s, run, stale, lease)
        finally:
            await lease.release()
        # Settings saved while it ran (an AI step approved just after a save) could not start their own rebuild, as
        # this one held the source: it rebuilds what they changed now, so they never wait for the next sync.
        found = await self.store.sources(who.tenant_id, [str(s.id)])
        if found and self.key_of(found[0]) != self.key_of(s):
            await self.start_rebuild(who, found[0])

    async def _rebuild_items(self, who: Who, s: SourceRow, run: RunWrite, stale: list[ItemRow], lease: Lease) -> None:
        tenant, source_id, run_id = who.tenant_id, str(s.id), str(run["id"])
        counts: dict[str, int] = dict(run["counts"])
        log: list[str] = []
        errors: list[RunError] = []
        status = "success"
        try:
            for item in stale:
                current = (await self.store.runs(tenant, run_id=run_id))[0]
                if current.cancelled_by:
                    status = "cancelled"
                    log.append(f"Cancelled by {current.cancelled_by} after {counts['checked']} of {counts['total']}.")
                    break
                counts["checked"] += 1
                if not item.file_id:
                    # Content read through a connection's tools keeps no copy yet: it is rebuilt when next fetched.
                    counts["skipped"] += 1
                    log.append(f"{item.title}: rebuilt at the next sync, which fetches it again")
                else:
                    found = Stored(item.file_id, item.path, item.mime, item.size, item.digest, False)
                    origin = Origin(item.path, item.title) if s.type == "tool" else None
                    done = await self._read_file(who, s, item, name=item.path, found=found, rebuild=True, origin=origin)
                    outcome = {"indexed": "rebuilt", "reading": "reading"}.get(done.status, "failed")
                    counts[outcome] += 1
                    if outcome == "failed":
                        errors.append(parse_error(done))
                await self.store.update_run(tenant, run_id, {"counts": dict(counts)})
            if status == "success" and counts["failed"]:
                status = "partial"
        except asyncio.CancelledError:
            status = "failed"
            log.append("Stopped when the service stopped; save the settings again or sync to finish.")
            raise
        finally:
            spent_on(counts, log)
            ended = datetime.now(UTC)
            await lease.finish(
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
            if counts["rebuilt"]:
                _, by_source = await self._joined(tenant)
                await self.store.refreshed(tenant, by_source.get(source_id, []))
                await self.embed_now(tenant)

    async def cancel_run(self, who: Who, run_id: str) -> RunView:
        """Asks a running rebuild to stop between two items; 409 when it is not running."""
        found = await self.store.runs(who.tenant_id, run_id=run_id)
        if not found:
            raise NotFound("No sync run with that id.")
        await self._changeable_source(who, found[0].source_id)
        if not await self.store.cancel_run(who.tenant_id, run_id, by=who.email):
            raise Conflict("This run is not running.", code="run_not_running")
        return _run((await self.store.runs(who.tenant_id, run_id=run_id))[0])

    async def _sync(
        self,
        who: Who,
        s: SourceRow,
        *,
        full: bool,
        retry: bool,
        trigger: str | None = None,
        only: str | None = None,
    ) -> RunView:
        """Reads every file of the source and indexes what changed: a new name is a new document, a known name with
        different content is its next version, identical content is unchanged. `full` rebuilds every document from its
        content and `retry` rebuilds the failed ones, both keeping their version. One file failing does not stop the
        rest; its item says why. Every sync is recorded as a run."""
        source_id = s.id
        if s.status == "paused":
            raise Conflict(f"{s.name} is paused; resume it to sync.", code="source_paused")
        started = datetime.now(UTC)
        settings = self.settings_of(s)
        items = {i.path: i for i in await self.store.items(who.tenant_id, source_ids=[source_id])}
        # Each name's digest, the store's or the one this run just read, for the same content under another name.
        digests = {name: i.digest for name, i in items.items()}
        counts = {"listed": 0, "unchanged": 0, "upserted": 0, "deleted": 0, "failed": 0, "skipped": 0, "excluded": 0}
        errors: list[RunError] = []
        log: list[str] = []
        # Each document is read from the last file uploaded under its name; an earlier file under the same name (left
        # by uploads before add_file replaced them) is dropped from the source, so it is neither indexed nor pending.
        latest: dict[str, Stored] = {}
        superseded: set[str] = set()
        uploaded: dict[str, str] = s.file_names or {}
        counts["reading"] = 0
        for file_id in s.file_ids if only is None else [f for f in s.file_ids if uploaded.get(f) == only]:
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
                    excluded.append(existing.id)
                continue
            # files-service's digest, the key documents-service keeps the file's reading under.
            same = existing is not None and existing.digest == found.digest and existing.status != "reading"
            stale = existing is not None and self.built_under_other_settings(s, existing)
            if same and existing is not None and not (stale or full or (retry and existing.status == "failed")):
                counts["unchanged"] += 1
                continue
            if not same and any(d == found.digest and other != name for other, d in digests.items()):
                # The same content under another name in this source: indexed once.
                counts["skipped"] += 1
                log.append(f"{name}: the same content is already indexed in this source")
                continue
            item = await self._read_file(who, s, existing, name=name, found=found, rebuild=same)
            digests[name] = item.digest
            if item.status == "failed":
                counts["failed"] += 1
                errors.append(parse_error(item))
            elif item.status == "reading":
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
        spent_on(counts, log)
        run: RunWrite = {
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
        return _run(run_row(run))

    async def _chunks(
        self, who: Who, s: SourceRow, doc: ParsedDocument, *, item_id: str, version: int, title: str
    ) -> tuple[list[PieceWrite], SplitResult]:
        """The item's pieces under the source's settings, each with its index units and its mapped metadata. With an
        approved AI step the split asks the model in a worker thread, on the run's client and ceiling, and only for
        pieces whose text has no questions yet."""
        settings = split_settings(self.settings_of(s))
        if not ai_steps_on(settings):
            result = split(doc, settings)
        else:
            with ai_run(self.ai_clients, who.tenant_id, ceiling=self.settings_of(s).ai_ceiling) as run:
                if run.client is None:
                    run.notes.add("Likely questions are on, but this stack has no models-service to write them.")
                    result = split(doc, settings.model_copy(update={"approval": IngestApproval()}))
                else:
                    known = await self._known_questions(who.tenant_id, item_id)
                    drafted = {str(detail_of(d).get("sectionDigest")) for d in await self._drafts(who, item_id)}
                    result = await asyncio.to_thread(
                        split,
                        doc,
                        settings,
                        model=run.client,
                        known_questions=known,
                        known_sections=drafted,
                    )
                    run.notes.update(n for n in result.notes if "stopped" in n)
        return pieces(who.tenant_id, item_id, version, title, result, self._metadata(s, doc)), result

    async def _drafts(self, who: Who, item_id: str) -> list[ChangeRow]:
        """The item's FAQ drafts that still stand (a superseded one was replaced by a newer draft of its section)."""
        return [d for d in await self.store.drafts(who.tenant_id, item_id) if d.status != "superseded"]

    async def _settle_drafts(
        self, who: Who, s: SourceRow, item_id: str, rows: list[PieceWrite], result: SplitResult
    ) -> None:
        """After a split: new drafts wait for review; a section whose text changed supersedes its pending drafts and
        marks its approved ones source_changed for a second look; every approved pair whose quote is still in a live
        piece is searchable again as a unit of that piece."""
        if not result.section_digests and not result.pairs:
            return
        now = datetime.now(UTC)
        live = set(result.section_digests)
        for d in await self._drafts(who, item_id):
            detail = detail_of(d)
            if detail.get("sectionDigest") in live:
                continue
            if d.status == "pending":
                await self.store.update_change(who.tenant_id, d.id, {"status": "superseded"})
            elif d.status == "approved":
                await self.store.update_change(who.tenant_id, d.id, {"status": "source_changed"})
        rows_by_index = {r["position"]: r for r in rows}
        drafts: list[DraftWrite] = [
            {
                "id": new_id("chg"),
                "item_id": item_id,
                "source_id": str(s.id),
                "title": rows_by_index[p.chunk_index]["title"],
                "section": " > ".join(p.section_path)[:400],
                "from_version": rows_by_index[p.chunk_index]["version"],
                "to_version": rows_by_index[p.chunk_index]["version"],
                "before": "",
                "after": f"Q: {p.question}\nA: {p.answer}",
                "changed_by": "FAQ drafts",
                "changed_at": now,
                "origin": "faq",
                "status": "pending",
                "detail": {
                    "question": p.question,
                    "answer": p.answer,
                    "quote": p.quote,
                    "sectionDigest": p.section_digest,
                    "sectionPath": [*p.section_path],
                },
            }
            for p in result.pairs
        ]
        await self.store.add_drafts(who.tenant_id, drafts)
        await self._faq_units(who, item_id)

    async def _faq_units(self, who: Who, item_id: str) -> int:
        """The item's approved pairs (and those whose source changed) as units of the live piece holding each quote,
        which search returns and cites; the number made. A pair whose quote is no longer in any piece makes none."""
        live = await self.store.chunks(who.tenant_id, item_id)
        units: list[FaqUnitWrite] = []
        for d in await self._drafts(who, item_id):
            if d.status not in ("approved", "source_changed"):
                continue
            detail = detail_of(d)
            quote = " ".join(str(detail.get("quote") or "").split()).lower()
            holder = next((c for c in live if quote and quote in " ".join(c.text.split()).lower()), None)
            if holder is None:
                continue
            heading = " ".join(p for p in (str(d.title), holder.section) if p)
            units.append(
                {
                    "id": new_id("unt"),
                    "chunk_id": holder.id,
                    "item_id": item_id,
                    "kind": "faq",
                    "position": FAQ_POSITION + len(units),
                    "heading": heading[:800],
                    "text": str(detail.get("question") or ""),
                }
            )
        await self.store.replace_faq_units(who.tenant_id, item_id, units)
        return len(units)

    async def decide_drafts(
        self, who: Who, ids: list[str], *, decision: str, edit: dict[str, str] | None = None, reason: str | None = None
    ) -> list[ChangeView]:
        """Approve, reject or edit FAQ drafts, each by the knowledge owner of its source. An approved pair is
        searchable at once (embedded with the rest of the tenant's units); an edit keeps it waiting for review."""
        found = {
            c.id: c
            for c in await self.store.changes(who.tenant_id, ids=ids)
            if c.origin == "faq" or "held" in detail_of(c)
        }
        if missing := [i for i in ids if i not in found]:
            raise NotFound(f"No FAQ draft or held change {missing[0]}.")
        items: set[str] = set()
        for change_id in ids:
            d = found[change_id]
            await self._changeable_source(who, str(d.source_id))
            if d.status not in DECIDABLE:
                raise Conflict(f"That draft is {d.status}; there is nothing to decide.", code="draft_decided")
            values: ChangeChanges = {"decided_by": who.email, "decided_at": datetime.now(UTC)}
            if decision != "edit":
                values["decision_reason"] = reason.strip() or None if reason else None
            if d.origin == "sync":
                # A version a sync held for review: approving indexes it; it cannot be edited.
                if decision == "edit":
                    raise Conflict("A synced version is approved or rejected, not edited.", code="draft_decided")
                values["status"] = "rejected"
                if decision == "approve":
                    values["status"] = "approved" if await self._apply_held(who, d) else "superseded"
                await self.store.update_change(who.tenant_id, change_id, values)
                continue
            if decision == "edit":
                detail: dict[str, JsonValue] = {**detail_of(d), **(edit or {})}
                values = {"detail": detail, "after": f"Q: {detail['question']}\nA: {detail['answer']}"}
            else:
                values["status"] = "approved" if decision == "approve" else "rejected"
            await self.store.update_change(who.tenant_id, change_id, values)
            items.add(str(d.item_id))
        for item_id in items:
            await self._faq_units(who, item_id)
        await self.embed_now(who.tenant_id)
        decided = {c["id"]: c for c in await self._changes_out(who, await self.store.changes(who.tenant_id, ids=ids))}
        return [decided[i] for i in ids]

    async def _known_questions(self, tenant: str, item_id: str) -> dict[str, list[str]]:
        """The questions the item's live pieces have, by piece_digest of their text: a piece split again with the same
        text keeps them, and the model is not asked again."""
        texts = {c.id: c.text for c in await self.store.chunks(tenant, item_id)}
        known: dict[str, list[str]] = {}
        for u in await self.store.units(tenant, item_id):
            if u.kind == "question" and u.chunk_id in texts:
                known.setdefault(piece_digest(texts[u.chunk_id]), []).append(u.text)
        return known

    def _metadata(self, s: SourceRow, doc: ParsedDocument) -> dict[str, str]:
        mapped = resolve_metadata(
            self.settings_of(s).metadata_mapping,
            fields=doc.source.fields,
            collection=str(s.collection),
            source_owner=str(s.owner),
            source_sensitivity=cast(Sensitivity, s.sensitivity),
        )
        return mapped.values

    async def _reindex(
        self,
        who: Who,
        s: SourceRow,
        existing: ItemRow,
        *,
        name: str,
        doc: ParsedDocument,
        read_with: str,
        title_given: str | None = None,
        lines: list[str] | None = None,
    ) -> Settled:
        """The same content split again from its stored reading under its current version: no new version, no change
        row, and the file's bytes are not read again."""
        error: tuple[str, str] | None = None
        warning: str | None = None
        title, pages = title_given or doc.title or name, doc.source.page_count
        settings = self.settings_of(s)
        chunks, result = await self._chunks(who, s, doc, item_id=existing.id, version=existing.version, title=title)
        if chunks:
            warning = _unread(doc)
        else:
            error = _empty(doc, settings.parsing.ocr)
        values: ItemChanges = {
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
        await self.store.reindex(who.tenant_id, existing.id, values, chunks)
        await self._settle_drafts(who, s, existing.id, chunks, result)
        return await self._duplicates(who, s, settled_row(existing, values))

    def built_under_other_settings(self, s: SourceRow, item: ItemRow) -> bool:
        """Whether an indexed item's pieces were split, or its file read, under settings the source no longer has.
        An item indexed before items recorded their settings was split with its kind's defaults."""
        if item.status != "indexed":
            return False
        settings = self.settings_of(s)
        built = item.indexed_with or index_key(stored(kind_of(s), None, ocr=self.ocr))
        read_ocr = (item.read_with or "").split(":")
        reread = s.type != "tool" and len(read_ocr) > 1 and read_ocr[1] != settings.parsing.ocr
        return built != self.key_of(s) or reread

    async def _read_file(
        self,
        who: Who,
        s: SourceRow,
        existing: ItemRow | None,
        *,
        name: str,
        found: Stored,
        rebuild: bool,
        origin: Origin | None = None,
    ) -> Settled:
        """One file of a source from its reading: indexed when the reading is ready, marked reading while
        documents-service reads it in the background (or is out of reach), failed with the reader's reason. A file
        source's item is keyed by its name; a fetched item gives its `origin` (the system's id, title and marker)."""
        origin = origin or Origin(name)
        if self.readings is None:
            return await self._failed(who, s, existing, name=name, found=found, error=NO_READER, origin=origin)
        try:
            ocr = self.settings_of(s).parsing.ocr
            answer = ReadingAnswer.model_validate(
                await self.readings.reading(who.tenant_id, source_team(s), found.file_id, ocr=ocr)
            )
        except DocumentsRefused as e:
            failed = ("parse", e.message)
            return await self._failed(who, s, existing, name=name, found=found, error=failed, origin=origin)
        except ServiceUnreachable:
            # The owner's rule: a sync waits for documents-service while it is down; the item stays queued.
            return await self._mark_reading(who, s, existing, name=name, found=found, origin=origin)
        status = answer.status
        if status in READING_PENDING:
            return await self._mark_reading(who, s, existing, name=name, found=found, origin=origin)
        if status != "done":
            reason = (answer.error.message if answer.error else None) or "the file could not be read"
            return await self._failed(who, s, existing, name=name, found=found, error=("parse", reason), origin=origin)
        cleaning = self.settings_of(s).cleaning
        # A fetched item's fields (from its fetch, or kept on it for a rebuild) feed the metadata mapping.
        kept_fields = {k: str(v) for k, v in existing.fields.items()} if existing and existing.fields else None
        fields = origin.extra.get("fields") or kept_fields
        doc = parsed_of(answer, fields=fields, furniture=cleaning.furniture, main_content=cleaning.main_content)
        # Each paragraph's digest is kept before lines repeated across the site are dropped, so they can be counted.
        lines = lines_of(doc)
        if cleaning.site_repeats:
            doc = without(doc, set(repeats_of(s)))
        if rebuild and existing is not None:
            return await self._reindex(
                who, s, existing, name=name, doc=doc, read_with=read_with(answer), title_given=origin.title, lines=lines
            )
        fetched: ItemFetched = {**origin.extra, "lines": lines}
        return await self._index(
            who, s, existing, file_id=found.file_id, name=name, mime=found.mime, doc=doc, size=found.size,
            digest=found.digest, read_with=read_with(answer), path=origin.path, extra=fetched,
            title_given=origin.title, allowed=origin.allowed,
        )  # fmt: skip

    async def _mark_reading(
        self, who: Who, s: SourceRow, existing: ItemRow | None, *, name: str, found: Stored, origin: Origin
    ) -> Settled:
        """The item waits for its reading; an indexed version keeps answering until the new one is indexed."""
        if existing is not None:
            values: ItemChanges = {
                "status": "reading",
                "digest": found.digest,
                "file_id": found.file_id,
                "mime": found.mime,
                "size": found.size,
                "error_class": None,
                "error": None,
            }
            await self.store.update_item(who.tenant_id, existing.id, values)
            return settled_row(existing, values)
        item = self._placeholder(who, s, name, found, origin)
        await self.store.add_item(who.tenant_id, item)
        return settled_new(item)

    async def _failed(
        self,
        who: Who,
        s: SourceRow,
        existing: ItemRow | None,
        *,
        name: str,
        found: Stored,
        error: tuple[str, str],
        origin: Origin | None = None,
    ) -> Settled:
        if existing is not None:
            values: ItemChanges = {"status": "failed", "error_class": error[0], "error": error[1],
                                   "digest": found.digest, "file_id": found.file_id,
                                   "processed_at": datetime.now(UTC)}  # fmt: skip
            await self.store.update_item(who.tenant_id, existing.id, values)
            return settled_row(existing, values)
        item = self._placeholder(who, s, name, found, origin or Origin(name))
        item["status"] = "failed"
        item["error_class"], item["error"], item["processed_at"] = error[0], error[1], datetime.now(UTC)
        await self.store.add_item(who.tenant_id, item)
        return settled_new(item)

    def _placeholder(self, who: Who, s: SourceRow, name: str, found: Stored, origin: Origin) -> ItemWrite:
        """An item with no version yet: its first indexed version is 1."""
        return {
            "tenant_id": who.tenant_id, "id": new_id("itm"), "source_id": s.id, "path": origin.path,
            "title": origin.title or name, "mime": found.mime, "size": found.size, "file_id": found.file_id,
            "digest": found.digest, "version": 0, "status": "reading", "chunk_count": 0, "owner": s.owner,
            "created_at": datetime.now(UTC), **origin.extra,
        }  # fmt: skip

    async def finish_reading(self, who: Who, file_id: str) -> int:
        """Indexes the source items waiting on this file's reading, once documents-service has it (its
        reading.finished event, or the knowledge schedule asking again); the number of items it settled."""
        settled = 0
        for item in await self.store.reading_items(who.tenant_id, file_id=file_id):
            found_sources = await self.store.sources(who.tenant_id, [item.source_id])
            if not found_sources:
                continue
            source = found_sources[0]
            found = Stored(item.file_id, item.path, item.mime, item.size, item.digest, False)
            # A fetched item keeps the system's id as its key and its own title; a file's title comes from its reading.
            origin = Origin(item.path, item.title) if source.type == "tool" else None
            done = await self._read_file(who, source, item, name=item.path, found=found, rebuild=False, origin=origin)
            if done.status != "reading":
                settled += 1
                if done.status == "indexed":
                    await self.settle_run(who, source, "success", activate=True)
                    _, by_source = await self._joined(who.tenant_id)
                    await self.store.refreshed(who.tenant_id, by_source.get(str(source.id), []))
        return settled

    async def _index(
        self,
        who: Who,
        s: SourceRow,
        existing: ItemRow | None,
        *,
        file_id: str,
        name: str,
        mime: str,
        digest: str,
        doc: ParsedDocument,
        size: int,
        read_with: str | None = None,
        path: str | None = None,
        extra: ItemFetched | None = None,
        title_given: str | None = None,
        allowed: list[str] | None = None,
    ) -> Settled:
        """The item's next version from its reading's document (`doc`): every file and every fetched item is read by
        documents-service, never here. `path` keys the document in its source (a file's name, or the system's id for
        a fetched item), `extra` adds a fetched item's marker, parent and address, and `title_given` is the system's
        own title for it."""
        now = datetime.now(UTC)
        cleaned = document_digest(doc, split_settings(self.settings_of(s)))
        if (
            existing is not None
            and existing.status == "indexed"
            and existing.content_digest == cleaned
            and not self.built_under_other_settings(s, existing)
        ):
            # The same text after cleaning (a page with no change signal, served with a new timestamp or token): no new
            # version. It keeps the snapshot just read and its markers, so the next run compares against them.
            kept: ItemChanges = {"file_id": file_id, "digest": digest, "size": size}
            fetched = extra or {}
            if "marker" in fetched:
                kept["marker"] = fetched["marker"]
            if "tag" in fetched:
                kept["tag"] = fetched["tag"]
            if "gone_count" in fetched:
                kept["gone_count"] = fetched["gone_count"]
            await self.store.update_item(who.tenant_id, existing.id, kept)
            return settled_row(existing, kept, unchanged=True)
        item_id = existing.id if existing else new_id("itm")
        version = (existing.version + 1) if existing else 1
        chunks: list[PieceWrite] = []
        error: tuple[str, str] | None = None
        warning: str | None = None
        settings = self.settings_of(s)
        title, pages = title_given or doc.title or name, doc.source.page_count
        chunks, result = await self._chunks(who, s, doc, item_id=item_id, version=version, title=title)
        if chunks:
            warning = _unread(doc)
        else:
            error = _empty(doc, settings.parsing.ocr)
        item: ItemWrite = {
            "tenant_id": who.tenant_id,
            "id": item_id,
            "source_id": s.id,
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
            "owner": s.owner,
            "created_at": existing.created_at if existing else now,
            "processed_at": now,
            "read_with": read_with,
            "indexed_with": None if error else self.key_of(s),
            "content_digest": None if error else document_digest(doc, split_settings(settings)),
            "duplicate_of": None,
            **(extra or {}),
        }
        version_row: VersionWrite = {
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
        if existing is not None and existing.version > 0:
            before = await self.store.chunks(who.tenant_id, item_id)
            change = _change(who, s, item, existing.version, before, chunks, now)
        if (
            change is not None
            and existing is not None
            and not error
            and existing.content_digest != item.get("content_digest")
            and (await self.sync_rules(who.tenant_id, str(s.id)))["changes"] == "review"
        ):
            return await self._hold(who, existing, item, version_row, chunks, change)
        await self.store.index_version(who.tenant_id, item, version_row, chunks, new=existing is None, change=change)
        await self._settle_drafts(who, s, item_id, chunks, result)
        return await self._duplicates(who, s, settled_new(item))

    async def _hold(  # noqa: PLR0917 - one call site, every argument a different part of the version
        self,
        who: Who,
        existing: ItemRow,
        item: ItemWrite,
        version_row: VersionWrite,
        chunks: list[PieceWrite],
        change: ChangeWrite,
    ) -> Settled:
        """A changed version a base feeding this source reviews: kept in Changes as a pending change with the version
        built, while search keeps serving the current one. Approving it indexes the version as built. The same content
        found again (still waiting, or rejected) is not held twice."""
        held = [c for c in await self.store.changes(who.tenant_id) if c.item_id == existing.id]
        digest = str(item.get("content_digest"))
        if any(c.origin == "sync" and detail_of(c).get("digest") == digest for c in held):
            return settled_row(existing, {}, unchanged=True)
        for c in held:
            if c.origin == "sync" and c.status == "pending":
                await self.store.update_change(who.tenant_id, str(c.id), {"status": "superseded"})
        held_version = HeldVersion(item=item, version=version_row, chunks=chunks)
        detail: dict[str, JsonValue] = {"digest": digest, "held": _json_safe(held_version)}
        # Written with the drafts' insert: one change row, waiting for a decision.
        draft: DraftWrite = {
            "id": change["id"],
            "item_id": change["item_id"],
            "source_id": change["source_id"],
            "title": change["title"],
            "section": change["section"],
            "from_version": change["from_version"],
            "to_version": change["to_version"],
            "before": change["before"],
            "after": change["after"],
            "changed_by": change["changed_by"],
            "changed_at": change["changed_at"],
            "status": "pending",
            "detail": detail,
        }
        await self.store.add_drafts(who.tenant_id, [draft])
        return settled_row(existing, {}, unchanged=True)

    async def _apply_held(self, who: Who, change: ChangeRow) -> bool:
        """Indexes the version a held change carries, as a sync would have when it found it; False when the document
        moved on since (its version is no longer the one the change started from), and nothing is indexed."""
        held = HELD_VERSION.validate_python(_from_json_safe(detail_of(change)["held"]))
        current = await self.store.items(who.tenant_id, source_ids=[change.source_id])
        now = next((i for i in current if i.id == change.item_id), None)
        if now is None or now.version != change.from_version:
            return False
        await self.store.index_version(
            who.tenant_id, held["item"], held["version"], held["chunks"], new=False, change=None
        )
        return True

    async def _duplicates(self, who: Who, s: SourceRow, item: Settled) -> Settled:
        """An item whose cleaned text another indexed item in the same knowledge base already holds. Flagged (the
        default): the older one names the newer and leaves search, and both say so. Skipped: the newer one is kept out
        of search and says which item holds the text."""
        digest = item.content_digest
        if item.status != "indexed" or not digest:
            return item
        same = await self.store.same_content(who.tenant_id, item.id, digest)
        if not same:
            return item
        names = ", ".join(sorted(d.title for d in same))
        if self.settings_of(s).cleaning.duplicates == "skip":
            skipped: ItemChanges = {
                "status": "skipped",
                "warning": f"Not indexed: the same text is already in {names}.",
            }
            await self.store.update_item(who.tenant_id, item.id, skipped)
            return replace(item, status="skipped")
        for d in same:
            await self.store.update_item(
                who.tenant_id,
                d.id,
                {"duplicate_of": item.id, "warning": f"Left out of search: {item.title} has the same text."},
            )
        flagged: ItemChanges = {"warning": f"Same text as {names}, which search now leaves out."}
        await self.store.update_item(who.tenant_id, item.id, flagged)
        return item

    # ── Retrieval ────────────────────────────────────────────────────────

    async def readable_bases(self, who: Who) -> list[BaseRow]:
        """Every base of the tenant for a service, which checks its callers' grants itself; for a person, those of
        their team and those no team owns."""
        if who.caller is not None and who.caller.kind == "service":
            return await self.store.bases(who.tenant_id)
        return await self.store.team_bases(who.tenant_id, who.team_id)

    async def search(
        self, who: Who, kb_ids: list[str], question: str, *, limit: int | None = None, collection: str | None = None
    ) -> Json:
        """Passages for `question` across `kb_ids` in the caller's tenant, best first, by the bases' own retrieval
        settings; empty when nothing reaches the threshold. Unknown ids are refused, never silently searched as empty,
        and a base a person may not read is unknown to them; a retired base is skipped, so an agent that still names it
        answers from its other bases. `limit`, when given, caps the pieces below what the bases allow."""
        tenant = who.tenant_id
        readable = {b.id: b for b in await self.readable_bases(who)}
        retired = await self.store.retired(tenant, [k for k in kb_ids if k not in readable])
        if missing := [k for k in kb_ids if k not in readable and k not in retired]:
            raise NotFound(f"No knowledge base with id {missing[0]}.")
        live = [k for k in dict.fromkeys(kb_ids) if k in readable]
        found = await self._retrieve(tenant, [readable[k] for k in live], question, limit=limit, collection=collection)
        out = found_out(found).model_dump(by_alias=True, exclude_unset=True)
        answers: dict[str, Answer] = {k: settings_of(readable[k])["answer"] for k in live}
        out["answers"] = answers
        return out

    async def _retrieve(
        self,
        tenant: str,
        bases: list[BaseRow],
        question: str,
        *,
        limit: int | None = None,
        collection: str | None = None,
    ) -> Found:
        """The one search every caller goes through: the question rewritten when a base asks, the lanes, then the best
        fused pieces reranked when a base asks. A step that fails leaves the search as it was and says why."""
        how = search_settings(bases, limit=limit, collection=collection)
        steps = steps_for(
            [{**narrow.an_object(DEFAULT_RETRIEVAL, "retrieval"), **b.retrieval} for b in bases], self.query_alias
        )
        searched: str = question
        rewrite: RewriteTrace | None = None
        deadline = asyncio.get_running_loop().time() + self.search_wait_s
        if steps.rewrite_alias is not None:
            started = time.monotonic()
            rewrite = {"asked": question, "rewritten": None}
            try:
                if self.query_model is None:
                    raise QueryStepFailed("no_query_model")
                async with asyncio.timeout_at(deadline):
                    searched = await self.query_model.rewrite(
                        question, steps.instruction, alias=steps.rewrite_alias, tenant=tenant
                    )
                rewrite["rewritten"] = searched
            except QueryStepFailed as e:
                rewrite["skipped"] = e.reason
            except TimeoutError:
                searched = question
                rewrite["skipped"] = "timeout"
            rewrite["ms"] = ms_since(started)
        pool = dataclasses.replace(how, limit=max(how.limit, RERANK_POOL)) if steps.rerank_alias else how
        found = await self.retriever.search(tenant, [b.id for b in bases], searched, pool, deadline=deadline)
        found = dataclasses.replace(found, rewrite=rewrite)
        if steps.rerank_alias is None:
            return found
        return await self._reranked(tenant, found, searched, steps.rerank_alias, how.limit, deadline=deadline)

    async def _reranked(
        self, tenant: str, found: Found, question: str, alias: str, limit: int, *, deadline: float
    ) -> Found:
        """The fused pieces in the order the reranker scores them, cut to the bases' limit; the fused order cut to it
        when the reranker cannot answer."""
        started = time.monotonic()
        pool = found.passages
        rerank: RerankTrace = {"ran": False, "model": alias, "scored": 0}
        passages = pool[:limit]
        if pool:
            try:
                if self.query_model is None:
                    raise QueryStepFailed("no_query_model")
                async with asyncio.timeout_at(deadline):
                    scores = await self.query_model.scores(question, [p.text for p in pool], alias=alias, tenant=tenant)
                ranked = sorted(
                    zip(pool, scores, strict=True), key=lambda ps: ps[1], reverse=True
                )  # sorted is stable, so equal scores keep the fused order
                passages = [dataclasses.replace(p, reranked=s) for p, s in ranked[:limit]]
                rerank["ran"], rerank["scored"] = True, len(pool)
            except QueryStepFailed as e:
                rerank["skipped"] = e.reason
            except TimeoutError:
                rerank["skipped"] = "timeout"
        rerank["ms"] = ms_since(started)
        return dataclasses.replace(found, passages=passages, rerank=rerank)

    async def query(self, who: Who, kb_id: str, question: str, *, collection: str | None = None) -> QueryView:
        """The query route and the console's Playground: the passages one knowledge base returns for a question, with
        each lane's score, which lanes ran, and the embedding tokens the question cost. No model writes an answer here;
        an answer is a kernel turn (agents-service), where the rule that withholds an uncited answer lives."""
        b = await self.store.base(who.tenant_id, kb_id)
        if b is None:
            raise NotFound("No knowledge base with that id.")
        if b.last_refreshed_at is None:
            raise Conflict("This knowledge base has not indexed anything yet; sync a source first.", code="not_indexed")
        started = datetime.now(UTC)
        found = await self._retrieve(who.tenant_id, [b], question, collection=collection)
        passages = found.passages
        sources = {s.id: s for s in await self.store.sources(who.tenant_id)}
        items = {i.id: i for i in await self.store.items(who.tenant_id)}

        def source_name(p: Passage) -> str:
            item = items.get(p.item_id)
            return sources[item.source_id].name if item and item.source_id in sources else ""

        return {
            "id": new_id("qry"),
            "question": question,
            "matchers": [],
            "answer": passages[0].snippet if passages else settings_of(b)["answer"]["noAnswerMessage"],
            "citations": [
                {
                    "n": n + 1,
                    "documentId": p.item_id,
                    "title": p.title,
                    "section": p.section,
                    **cast(CitationParts, {"page": p.page} if p.page else {}),
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
            **cast(FoundParts, {"noAnswer": True} if not passages else {}),
            **cast(FoundParts, found_out(found).model_dump(by_alias=True, exclude_unset=True)),
            "retrievalMs": int((datetime.now(UTC) - started).total_seconds() * 1000),
            "synthesisMs": 0,
            "shape": "chunks",
        }

    async def embedding_coverage(self, who: Who, kb_id: str) -> EmbeddingView | None:
        """How many of the base's units have a vector of the environment's model; None without one."""
        if self.embedder is None or self.vectors is None or not await self.vectors.ready():
            return None
        embedded, total = await self.vectors.coverage(
            who.tenant_id, [kb_id], model=self.embedder.model, width=self.embedder.width
        )
        return {"model": self.embedder.model, "width": self.embedder.width, "embedded": embedded, "units": total}

    # ── Runs, source settings, refresh ───────────────────────────────────

    async def source_runs(self, who: Who, source_id: str, q: ListParams) -> ListPage:
        await self._source_row(who, source_id)
        page, runs = await self.store.run_page(who.tenant_id, source_id, q)
        page["data"] = [{**_run(r)} for r in runs]
        return page

    async def get_run(self, who: Who, run_id: str) -> RunView:
        found = await self.store.runs(who.tenant_id, run_id=run_id)
        if not found:
            raise NotFound("No sync run with that id.")
        return _run(found[0])

    async def update_source(self, who: Who, source_id: str, patch: SourcePatchInput) -> SourceRebuilt:
        s = await self._changeable_source(who, source_id)
        values: SourceChanges = {}
        if (name := patch.get("name")) is not None:
            if not str(name).strip():
                raise ValidationFailed("Give the source a name.")
            values["name"] = str(name).strip()
        if (sensitivity := patch.get("sensitivity")) is not None:
            if sensitivity not in SENSITIVITIES:
                raise ValidationFailed(f"Sensitivity is one of {', '.join(SENSITIVITIES)}.")
            values["sensitivity"] = sensitivity
        if (owner := patch.get("owner")) is not None:
            if not str(owner).strip():
                raise ValidationFailed("A source always has an owner.")
            values["owner"] = str(owner).strip()
        if (collection := patch.get("collection")) is not None:
            values["collection"] = collection
        if (tags := patch.get("tags")) is not None:
            values["tags"] = tags
        if (own := patch.get("values")) is not None:
            values["config"] = await self._values_changed(who, s, json_object(own))
        given = {k: v for k in SETTINGS_KEYS if (v := patch.get(k)) is not None}
        before = self.settings_of(s)
        if given:
            values["settings"] = wire(self._merged(before, given))
        if values:
            entry = audit_entry(
                who, "knowledge.source.settings", "knowledge_source", source_id, s.name, s.model_dump(), values
            )
            await self.store.update_source(who.tenant_id, source_id, values, audit=entry)
        _, by_source = await self._joined(who.tenant_id)
        after = s.model_copy(update=values)
        rebuild = None
        if given and rebuild_for(before, self.settings_of(after)) != "none":
            rebuild = await self.start_rebuild(who, after)
        return {**self._source(after, by_source.get(source_id, [])), "rebuild": rebuild}

    async def _values_changed(self, who: Who, s: SourceRow, given: Json) -> Json:
        """A plugin source's own settings (a site's start, include and exclude rules, depth, pace), merged over the
        saved ones and checked against what its plugin declares, as a create checks them."""
        if s.type != "tool":
            raise ValidationFailed("Only a source read through an app has settings of its own.")
        cfg: Json = dict(s.config or {})
        merged = {**json_object(cfg.get("values")), **given}
        checked = await source_config(
            self.tools, who, {"plugin": cfg.get("plugin"), "source": cfg.get("source"), "values": merged}
        )
        return {**cfg, "values": checked["values"]}

    async def decide_ai_steps(self, who: Who, source_id: str, *, approve: bool) -> SourceRebuilt:
        """The knowledge owner's approval of the source's AI steps as now chosen, or its revocation; the one audit log
        records it as a settings change, and a change in what the split asks the model rebuilds the pieces."""
        s = await self._changeable_source(who, source_id)
        before = self.settings_of(s)
        chosen = [step for step in before.ingest.strategies if step in AI_STEPS]
        if approve and not chosen:
            raise ValidationFailed("Choose an AI step (likely questions) before approving it.")
        approval = IngestApproval(
            status="approved" if approve else "pending" if chosen else "not_needed",
            approved_steps=chosen if approve else [],
            requested_by=before.ingest.approval.requested_by,
            decided_by=who.email,
            decided_at=datetime.now(UTC).isoformat(),
        )
        after = before.model_copy(update={"ingest": before.ingest.model_copy(update={"approval": approval})})
        values: SourceChanges = {"settings": wire(after)}
        entry = audit_entry(
            who, "knowledge.source.settings", "knowledge_source", source_id, s.name, s.model_dump(), values
        )
        await self.store.update_source(who.tenant_id, source_id, values, audit=entry)
        changed = s.model_copy(update=values)
        rebuild = None
        if rebuild_for(before, self.settings_of(changed)) != "none":
            rebuild = await self.start_rebuild(who, changed)
        _, by_source = await self._joined(who.tenant_id)
        return {**self._source(changed, by_source.get(source_id, [])), "rebuild": rebuild}

    async def estimate_ai_steps(self, who: Who, source_id: str) -> AiEstimateView:
        """The chosen AI steps' calls and tokens, from a preview split of up to ESTIMATE_SAMPLE indexed items with a
        model that answers nothing (no call is made), scaled to every indexed item of the source."""
        s = await self._source_row(who, source_id)
        settings = split_settings(self.settings_of(s))
        steps = [step for step in settings.strategies if step in AI_STEPS]
        indexed = [i for i in await self.store.items(who.tenant_id, source_ids=[source_id]) if i.status == "indexed"]
        sample = indexed[:ESTIMATE_SAMPLE]
        counter = CountingModel()
        read = 0
        for item in sample if steps else []:
            doc = await self._stored_document(who, s, item)
            if doc is not None:
                await asyncio.to_thread(split, doc, settings, model=counter, preview=True)
                read += 1
        scale = len(indexed) / read if read else 0.0
        return {
            "steps": steps,
            "model": settings.model,
            "sampledItems": read,
            "totalItems": len(indexed),
            "calls": round(counter.calls * scale),
            "inputTokens": round(counter.input_tokens * scale),
            "outputTokens": {
                "low": round(counter.calls * scale * OUTPUT_LOW),
                "high": round(counter.calls * scale * OUTPUT_HIGH),
            },
            "basis": (
                f"A split of {read} of {len(indexed)} indexed items, scaled to all; one call per piece, input counted "
                f"from the prompts at about four characters a token, output {OUTPUT_LOW} to {OUTPUT_HIGH} tokens a "
                "call. A sync asks again only for pieces whose text changed. The price per token is the alias's at "
                "models-service and is not included."
            ),
        }

    async def _stored_document(self, who: Who, s: SourceRow, item: ItemRow) -> ParsedDocument | None:
        """The item's document as its last split read it, from documents-service's kept reading; None when there is
        no reading to read now."""
        if self.readings is None or not item.file_id:
            return None
        try:
            ocr = self.settings_of(s).parsing.ocr
            answer = ReadingAnswer.model_validate(
                await self.readings.reading(who.tenant_id, source_team(s), item.file_id, ocr=ocr)
            )
        except (DocumentsRefused, ServiceUnreachable):
            return None
        if answer.status != "done":
            return None
        cleaning = self.settings_of(s).cleaning
        fields = {k: str(v) for k, v in item.fields.items()} if item.fields else None
        doc = parsed_of(answer, fields=fields, furniture=cleaning.furniture, main_content=cleaning.main_content)
        return without(doc, set(repeats_of(s))) if cleaning.site_repeats else doc

    async def tombstones(self, who: Who, source_id: str) -> list[Tombstone]:
        """The addresses removed after answering gone twice, with when and why; the next sync leaves them out."""
        s = await self._source_row(who, source_id)
        marks = json_object(json_object(s.config).get("tombstones"))
        return [
            Tombstone(id=k, at=narrow.field(mark, "at", str), reason=narrow.field(mark, "reason", str))
            for k, mark in ((k, json_object(v)) for k, v in sorted(marks.items()))
        ]

    async def lift_tombstones(self, who: Who, source_id: str, ids: list[str]) -> list[Tombstone]:
        """Lets the next sync take those addresses in again, if the source still lists them."""
        s = await self._changeable_source(who, source_id)
        cfg: Json = dict(s.config or {})
        marks = dict(narrow.an_object(cfg.get("tombstones") or {}, "tombstones"))
        if missing := [i for i in ids if i not in marks]:
            raise NotFound(f"No tombstone for {missing[0]}.")
        cfg["tombstones"] = {k: v for k, v in marks.items() if k not in ids}
        await self.store.update_source(who.tenant_id, source_id, {"config": cfg})
        return await self.tombstones(who, source_id)

    @staticmethod
    def _merged(current: SourceSettings, given: dict[str, JsonValue]) -> SourceSettings:
        try:
            return merged(current, given)
        except InvalidSettings as e:
            raise ValidationFailed(str(e), code="invalid_settings") from e

    async def set_paused(self, who: Who, source_id: str, *, paused: bool) -> SourceView:
        s = await self._changeable_source(who, source_id)
        status = "paused" if paused else "active"
        await self.store.update_source(who.tenant_id, source_id, {"status": status})
        _, by_source = await self._joined(who.tenant_id)
        return self._source(s.model_copy(update={"status": status}), by_source.get(source_id, []))

    async def detach(self, who: Who, kb_id: str, source_id: str) -> BaseView:
        b = await self._changeable(who, kb_id)
        await self.store.detach(who.tenant_id, kb_id, source_id)
        by_kb, _ = await self._joined(who.tenant_id)
        return self._base(b, by_kb.get(kb_id, []), await self._counts(who.tenant_id))

    async def refresh(self, who: Who, kb_id: str, *, retry: bool = False) -> BaseView:
        """Syncs every source the knowledge base reads that is not paused (the knowledge base's owner keeps what it
        serves current, whoever owns each source); `retry` rebuilds only the failed documents."""
        b = await self._changeable(who, kb_id)
        by_kb, _ = await self._joined(who.tenant_id)
        for s in await self.store.sources(who.tenant_id, by_kb.get(kb_id, [])):
            if s.status != "paused":
                try:
                    await self._held_sync(who, s, full=False, retry=retry)
                except Conflict:
                    # Running now: that run brings it up to date.
                    continue
        fresh = await self.store.base(who.tenant_id, kb_id)
        return self._base(
            fresh or b,
            by_kb.get(kb_id, []),
            await self._counts(who.tenant_id),
            await self._jobs(who.tenant_id, by_kb.get(kb_id, [])),
        )

    # ── Item review and lookups ──────────────────────────────────────────

    async def _changeable_item(self, who: Who, item_id: str) -> tuple[ItemRow, SourceRow]:
        found = await self.store.items(who.tenant_id, item_id=item_id)
        if not found:
            raise NotFound("No item with that id.")
        i = found[0]
        s = await self._source_row(who, i.source_id)
        self._may_change(who, s.team_id, i.title)
        return i, s

    async def verify_item(self, who: Who, item_id: str, *, verified: bool) -> ItemView:
        i, s = await self._changeable_item(who, item_id)
        values: ItemChanges = {
            "verified": verified,
            "verified_by": who.email if verified else None,
            "verified_at": datetime.now(UTC) if verified else None,
        }
        await self.store.update_item(who.tenant_id, item_id, values)
        return self._item(i.model_copy(update=values), s, await self._copies(who, [i]))

    async def set_item_owner(self, who: Who, item_id: str, owner: str) -> ItemView:
        if not owner.strip():
            raise ValidationFailed("A document always has an owner.")
        i, s = await self._changeable_item(who, item_id)
        await self.store.update_item(who.tenant_id, item_id, {"owner": owner.strip()})
        return self._item(i.model_copy(update={"owner": owner.strip()}), s, await self._copies(who, [i]))

    async def lookups(self, who: Who) -> dict[str, list[str]]:
        bases = await self.store.bases(who.tenant_id)
        sources = await self.store.sources(who.tenant_id)
        owners = (
            {b.owner for b in bases}
            | {s.owner for s in sources}
            | {i.owner for i in await self.store.items(who.tenant_id)}
        )
        tags = {t for s in sources for t in s.tags}
        collections = {c for b in bases for c in b.collections} | {s.collection for s in sources}
        return {
            "owners": sorted(o for o in owners if o),
            "tags": sorted(tags),
            "collections": sorted(c for c in collections if c),
        }

    # ── Changes ──────────────────────────────────────────────────────────

    async def _changes_out(self, who: Who, found: list[ChangeRow]) -> list[ChangeView]:
        """Changes as the Changes queue shows them; the sources and bases they name are read once for all of them."""
        if not found:
            return []
        sources = {s.id: s for s in await self.store.sources(who.tenant_id)}
        bases = {b.id: b for b in await self.store.bases(who.tenant_id)}
        _, by_source = await self._joined(who.tenant_id)
        return [self._change_out(who, ch, sources, bases, by_source) for ch in found]

    def _change_out(
        self,
        who: Who,
        ch: ChangeRow,
        sources: dict[str, SourceRow],
        bases: dict[str, BaseRow],
        by_source: dict[str, list[str]],
    ) -> ChangeView:
        s = sources.get(ch.source_id)
        kbs: list[KbRef] = [{"id": k, "name": bases[k].name} for k in by_source.get(ch.source_id, []) if k in bases]
        if ch.origin == "faq":
            # Deciding a draft is changing the source, so it takes the right the decide route checks.
            allowed = s is not None and self._rights(who, s.team_id, s.name, None)["canEdit"]
            draft = _draft_out(ch, s, kbs)
            return {**draft, **self.review_state(s), "canDecide": allowed and ch.status in DECIDABLE}
        held = "held" in detail_of(ch)
        waiting = held and ch.status in DECIDABLE
        return {
            "id": ch.id,
            "summary": f"{ch.title} changed from v{ch.from_version} to v{ch.to_version}",
            "origin": SHOWN_ORIGIN["sync"],
            "proposedBy": ch.changed_by,
            "rationale": (
                "A sync found a newer version; it is searched once approved."
                if held
                else "A newer file replaced the document when its source was synced."
            ),
            "documentId": ch.item_id,
            "documentTitle": ch.title,
            "sourceId": ch.source_id,
            "sourceName": s.name if s else "",
            "section": ch.section,
            "kbs": kbs,
            "fromVersion": f"v{ch.from_version}",
            "toVersion": f"v{ch.to_version}",
            "before": ch.before,
            "after": ch.after,
            "trust": "changed",
            **self.review_state(s),
            "citedBy": [],
            "owner": s.owner if s else "",
            # A sync applies its change when it runs, unless a base it feeds holds changes for review.
            "canDecide": waiting and s is not None and self._rights(who, s.team_id, s.name, None)["canEdit"],
            "status": ch.status if held else "approved",
            "createdAt": _iso(ch.changed_at),
            **cast(
                Decided,
                {
                    "decidedAt": _iso(ch.decided_at or ch.changed_at),
                    "decidedBy": ch.decided_by or ch.changed_by,
                    "decisionReason": ch.decision_reason,
                }
                if not waiting
                else {},
            ),
        }

    async def list_changes(
        self,
        who: Who,
        *,
        view: str,
        kb_id: str | None,
        page: int,
        page_size: int,
        search: str | None,
        origin: list[str] | None = None,
    ) -> ChangeListView:
        """A sync's change is applied when it runs; an FAQ draft waits for the knowledge owner (open) until decided.
        The From facet counts the view before it is filtered by origin, so every origin shows its count."""
        size = max(1, min(page_size, MAX_PAGE_SIZE))
        origins = None if not origin else [CHANGE_ORIGINS.get(o, o) for o in origin]
        found = await self.store.change_page(
            who.tenant_id,
            view=view,
            owner=who.email,
            kb_id=kb_id,
            search=search,
            origins=origins,
            page=page,
            page_size=size,
        )
        facets = {"origin": {SHOWN_ORIGIN.get(o, o): n for o, n in found.origins.items()}}
        return {
            "data": await self._changes_out(who, found.rows),
            "pagination": pagination(found.total, page, size),
            "facets": facets,
            "viewCounts": {**found.views, "conflicts": 0},
        }

    async def get_change(self, who: Who, change_id: str) -> ChangeView:
        found = await self.store.changes(who.tenant_id, ids=[change_id])
        if not found:
            raise NotFound("No change with that id.")
        [out] = await self._changes_out(who, found)
        return out

    # ── Items and documents ──────────────────────────────────────────────

    async def _copies(self, who: Who, items: list[ItemRow]) -> dict[str, CopyName]:
        """The copies the page's duplicates repeat, by id, read in one statement and only when a row is a
        duplicate; a copy the caller's team cannot see is not in it."""
        ids = sorted({i.duplicate_of for i in items if i.duplicate_of})
        return {c.id: c for c in await self.store.copy_names(who.tenant_id, ids)} if ids else {}

    def _item(self, i: ItemRow, s: SourceRow, copies: dict[str, CopyName] | None = None) -> ItemView:
        copy = (copies or {}).get(i.duplicate_of) if i.duplicate_of else None
        return {
            "id": i.id,
            "sourceId": i.source_id,
            "externalId": i.file_id,
            "title": i.title,
            "mimeType": i.mime,
            "path": i.path,
            **(ItemParts(url=i.url) if i.url else ItemParts()),
            "modifiedAt": _iso(i.processed_at or i.created_at),
            **(ItemParts(processedAt=_iso(i.processed_at)) if i.processed_at else ItemParts()),
            "sizeBytes": i.size,
            # The console's word for a document being read is processing.
            "status": SHOWN_STATUS.get(i.status, i.status),
            **(ItemParts(errorClass=i.error_class, error=i.error) if i.error_class else ItemParts()),
            **(ItemParts(warning=i.warning) if i.warning else ItemParts()),
            **(ItemParts(duplicateOf=i.duplicate_of) if i.duplicate_of else ItemParts()),
            **(ItemParts(duplicateCopy={"title": copy.title, "sourceName": copy.source_name}) if copy else ItemParts()),
            **(ItemParts(folder=i.folder) if i.folder else ItemParts()),
            "chunkCount": i.chunk_count,
            "tags": s.tags,
            "metadata": {},
            "acl": [],
            "owner": i.owner,
            "version": f"v{i.version}",
            "effectiveDate": (i.processed_at or i.created_at).date().isoformat(),
            **self.review_state(s),
            "sensitivity": s.sensitivity,
            "collection": s.collection,
            "verified": i.verified,
            "queries30d": 0,
            **(ItemParts(pageCount=i.page_count) if i.page_count else ItemParts()),
            "fileId": i.file_id,
            "digest": i.digest,
            "family": i.id,
            "versionStatus": "current",
        }

    async def source_items(self, who: Who, source_id: str, q: ListParams) -> ListPage:
        s = await self._source_row(who, source_id)
        page, items = await self.store.item_page(who.tenant_id, source_id, q)
        copies = await self._copies(who, items)
        page["data"] = [{**self._item(i, s, copies)} for i in items]
        # Counted as stored; shown under the console's names, so an item being read counts as processing.
        shown: dict[str, int] = {}
        for status, n in page["facets"].get("status", {}).items():
            name = SHOWN_STATUS.get(status, status)
            shown[name] = shown.get(name, 0) + n
        page["facets"]["status"] = shown
        return page

    async def add_page(self, who: Who, kb_id: str, title: str, text: str) -> Json:
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
        name = f"{b.name} pages"
        attached = await self.store.sources(who.tenant_id, by_kb.get(kb_id, []))
        source = next((x for x in attached if x.name == name), None)
        if source is None:
            made = await self.create_source(
                who, {"type": "text", "name": name, "collection": "Pages", "owner": b.owner, "kbIds": [kb_id]}
            )
            source_id = str(made["id"])
        else:
            source_id = source.id
            if source.type == "file":
                # A base's pages source made before typed text existed holds its pages as files; it becomes the typed
                # text source it always was, keeping its files and versions, so the next page is written into it.
                await self.store.update_source(who.tenant_id, source_id, {"type": "text"})
        put = await self.put_item(who, source_id, {"name": f"{_slug(title) or 'page'}.md", "title": title,
                                                            "text": text})  # fmt: skip
        return json_object(put["item"])

    async def put_item(self, who: Who, source_id: str, i: ItemInput) -> WrittenItemView:
        """One item written into a typed text or push source, by its `name`: stored as a file through files-service
        like an upload, then indexed by the source's sync. The same name with the same content is `unchanged` and
        starts no run, so a caller may send it again safely; the same name with new content is its next version.
        `text` is Markdown (a `title` becomes its heading) or another text type by `mime`; `content` is base64 bytes
        of a file such as a PDF, with its `mime`."""
        s = await self._changeable_source(who, source_id)
        if s.type not in WRITTEN_TYPES:
            raise ValidationFailed(
                f"{s.name} takes its items from {KIND_LABEL.get(kind_of(s), s.type)}; items are written only "
                "into a typed text or push source.",
                code="source_not_written",
            )
        name, title = str(i.get("name") or "").strip(), str(i.get("title") or "").strip()
        if not name:
            raise ValidationFailed("Give the item a name, such as escrow-analysis.md.")
        data, mime = written_bytes(i, title)
        if not name.endswith(tuple(WRITTEN_TEXT_MIMES.values())) and mime in WRITTEN_TEXT_MIMES:
            # The reader takes a written item's type from its name, as it does an upload's.
            name = f"{name}{WRITTEN_TEXT_MIMES[mime]}"
        before = next(
            (x for x in await self.store.items(who.tenant_id, source_ids=[source_id]) if x.path == name), None
        )
        stored_file = await self.upload(who, source_id, data, name=name, mime=mime)
        same = before is not None and before.digest == stored_file["digest"] and before.status == "indexed"
        log: list[str] = []
        if not same:
            # The same run as a sync, reading only this item: the source's other items are as they were.
            run = await self._held_sync(who, await self._source_row(who, source_id), full=False, retry=False, only=name)
            log = [str(x) for x in cast(list[object], run.get("log") or [])]
        found = (await self.store.sources(who.tenant_id, [source_id]))[0]
        item = next((x for x in await self.store.items(who.tenant_id, source_ids=[source_id]) if x.path == name), None)
        if item is None:
            # Stored, but the run made no item: files-service holds a new file unreadable until its scan says clean
            # (production scans every file), or a rule or the same content under another name left it out.
            why = next((x for x in log if x.startswith(f"{name}:")), "")
            if "not scanned" in why:
                raise Conflict(
                    f"{name} is stored but not scanned clean yet, so it is not searchable; it is read on the next sync "
                    "after the scan, or send it again then.",
                    code="file_not_ready",
                )
            # A rule of the source or the same content under another name: what was sent, so the caller's to change.
            raise ValidationFailed(
                f"{name} is stored but was not indexed: {why or 'the run made no item for it'}.",
                code="item_not_indexed",
            )
        url = str(i.get("url") or "").strip() or None
        if url and item.url != url:
            await self.store.update_item(who.tenant_id, item.id, {"url": url})
            item = item.model_copy(update={"url": url})
        outcome = "unchanged" if same else "created" if before is None else "updated"
        return {"outcome": outcome, "item": self._item(item, found, await self._copies(who, [item]))}

    async def add_documents(self, who: Who, kb_id: str, file_ids: list[str]) -> AddedDocumentsView:
        """Files from Files added to the base: into its own documents source, made and attached the first
        time, then synced at once, which also activates the source. Returns the source id, the files and the run."""
        b = await self._changeable(who, kb_id)
        by_kb, _ = await self._joined(who.tenant_id)
        own = b.documents_source_id
        source = None
        if own and own in by_kb.get(kb_id, []):
            source = (await self.store.sources(who.tenant_id, [str(own)]) or [None])[0]
        made = source is None
        if source is not None:
            source_id = source.id
        else:
            created = await self.create_source(
                who,
                {
                    "type": "file",
                    "name": f"{b.name} documents",
                    "collection": "Documents",
                    "owner": b.owner,
                    "kbIds": [kb_id],
                },
            )
            source_id = str(created["id"])
        try:
            added = await self.add_files(who, source_id, file_ids)
        except (UnknownFile, Conflict):
            # Files records a reference against the source, so it is made before the check; a refused first add must
            # not leave the base an empty documents source.
            if made:
                await self.store.remove_source(who.tenant_id, source_id)
            raise
        if made:
            await self.store.update_base(who.tenant_id, kb_id, {"documents_source_id": source_id})
        run = await self.sync(who, source_id)
        return {"sourceId": source_id, "files": added, "run": run}

    async def documents(self, who: Who, kb_id: str, q: ListParams) -> ListPage:
        """The base's documents, chosen, counted and paged in SQL; a source's freshness and tags, which the filters and
        facets read, are worked out here from the base's sources."""
        if await self.store.base(who.tenant_id, kb_id) is None:
            raise NotFound("No knowledge base with that id.")
        by_kb, _ = await self._joined(who.tenant_id)
        sources = {s.id: s for s in await self.store.sources(who.tenant_id, by_kb.get(kb_id, []))}
        freshness = {sid: self.freshness_of(s) for sid, s in sources.items()}
        tags = {sid: s.tags for sid, s in sources.items()}
        page, items = await document_page(self.store, who.tenant_id, kb_id, q, freshness=freshness, tags=tags)
        copies = await self._copies(who, items)
        page["data"] = [
            {
                **self._item(i, sources[i.source_id], copies),
                "sourceName": sources[i.source_id].name,
                "docType": doc_type(i.mime, sources[i.source_id].type, bool(i.url)),
            }
            for i in items
        ]
        page["facets"] = {key: page["facets"].get(key, {}) for key in DOCUMENT_FACETS}
        return page

    async def _reading_summary(self, who: Who, s: SourceRow, i: ItemRow) -> ItemReading | None:
        """How the item's file was read and what cleaning removed, page by page, from its stored reading; None for an
        item with no file or while documents-service has no finished reading for it."""
        if self.readings is None or not i.file_id:
            return None
        settings = self.settings_of(s)
        ocr = settings.parsing.ocr
        try:
            answer = await self.readings.reading(who.tenant_id, source_team(s), i.file_id, ocr=ocr)
        except (DocumentsRefused, ServiceUnreachable):
            return None
        if answer.get("status") != "done":
            return None
        cleaning = settings.cleaning
        pages = [json_object(p) for p in json_list(answer.get("pages"))]
        blocks_of = [[json_object(b) for b in json_list(p.get("blocks"))] for p in pages]
        has_main = cleaning.main_content and any(b.get("main") for blocks in blocks_of for b in blocks)

        def dropped(b: Json) -> bool:
            if cleaning.furniture and b.get("furniture"):
                return True
            return has_main and not b.get("main") and b.get("kind") != "title"

        out: list[ReadingPage] = []
        for page, blocks in zip(pages, blocks_of, strict=True):
            kinds: dict[str, int] = {}
            for b in blocks:
                if not dropped(b):
                    kinds[str(b.get("kind"))] = kinds.get(str(b.get("kind")), 0) + 1
            quality = json_object(page.get("ocr"))
            removed = sum(len(str(b.get("text") or "")) for b in blocks if dropped(b))
            number, read_by = narrow.field(page, "number", int), narrow.field(page, "source", str)
            # `ocrConfidence` only when the page has an OCR quality: the reply is dumped with `exclude_unset`.
            out.append(
                ReadingPage(number=number, read_by=read_by, blocks=kinds, removed_chars=removed)
                if not quality
                else ReadingPage(
                    number=number,
                    read_by=read_by,
                    blocks=kinds,
                    removed_chars=removed,
                    ocr_confidence=narrow.field(quality, "mean", float),
                )
            )
        return ItemReading(reader_version=narrow.field(answer, "readerVersion", str), ocr=ocr, pages=out)

    async def item(self, who: Who, item_id: str) -> ItemDetailView:
        """The item, its source, pieces, versions and copy read in one transaction; then, with none open,
        documents-service's reading of its file."""
        async with isolation.request_transaction():
            found = await self.store.items(who.tenant_id, item_id=item_id)
            if not found:
                raise NotFound("No item with that id.")
            i = found[0]
            s = await self._source_row(who, i.source_id)
            chunks = await self.store.chunks(who.tenant_id, item_id)
            units = await self.store.units(who.tenant_id, item_id)
            versions = await self.store.versions(who.tenant_id, item_id)
            copies = await self._copies(who, [i])
        searched: dict[str, list[SearchedAs]] = {}
        for u in units:
            searched.setdefault(u.chunk_id, []).append({"kind": u.kind, "text": u.text})
        reading = await self._reading_summary(who, s, i)
        settings = self.settings_of(s)
        return {
            **self._item(i, s, copies),
            "reading": reading.model_dump(by_alias=True, exclude_unset=True) if reading else None,
            "settingsUsed": {
                "preset": settings.ingest.preset,
                "strategies": settings.ingest.strategies,
                "indexedWith": i.indexed_with,
                "current": not self.built_under_other_settings(s, i),
            },
            "sourceName": s.name,
            "sourceType": s.type,
            "detail": {
                "content": "\n\n".join(c.text for c in chunks),
                "chunks": [
                    {
                        "index": c.position,
                        "tokens": c.tokens,
                        "location": _location(c.section, c.page),
                        **cast(CitationParts, {"page": c.page} if c.page else {}),
                        "kind": "content",
                        "text": c.text,
                        # What search matches for this piece: its own text, its children and its questions.
                        "units": searched.get(c.id, []),
                        "metadata": c.metadata or {},
                    }
                    for c in chunks
                ],
                "revisions": [],
                "versions": [
                    {
                        "itemId": item_id,
                        "title": i.title,
                        "version": f"v{v.version}",
                        "effectiveDate": v.created_at.date().isoformat(),
                        "status": v.status,
                        "digest": v.digest,
                        "sourceName": s.name,
                        # Who the source system lets see this version; stored, not yet enforced.
                        **cast(Allowed, {"allowed": v.allowed} if v.allowed else {}),
                    }
                    for v in versions
                ],
            },
        }


def _change(  # noqa: PLR0917 - one call site, every argument a different part of the change
    who: Who,
    s: SourceRow,
    item: ItemWrite,
    from_version: int,
    before: list[ChunkRow],
    after: list[PieceWrite],
    at: datetime,
) -> ChangeWrite:
    """The change a re-sync made: the first section whose text differs, before and after."""
    old = {c.section: c.text for c in reversed(before)}
    new = {c["section"]: c["text"] for c in reversed(after)}
    section = next((k for k in [*new, *old] if old.get(k) != new.get(k)), "")
    return {
        "tenant_id": who.tenant_id,
        "id": new_id("chg"),
        "item_id": item["id"],
        "source_id": s.id,
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
    before: Mapping[str, JsonValue],
    values: BaseChanges | SourceChanges,
) -> AuditEntry | None:
    """The audit entry for a settings change: who made it, which fields changed, and each field before and after
    (for a nested setting, its changed keys). None when nothing changed. The seed, with no caller, is not audited."""
    if who.caller is None:
        return None
    changes: Json = {}
    for key, after in values.items():
        old = before.get(key)
        if old == after:
            continue
        was, now = json_object(old), json_object(after)
        if isinstance(old, dict) and isinstance(after, dict):
            keys = sorted(k for k in {*was, *now} if was.get(k) != now.get(k))
            changes[key] = {k: {"from": was.get(k), "to": now.get(k)} for k in keys}
        else:
            changes[key] = {"from": old, "to": cast(JsonValue, after)}
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


def new_source(row: SourceRow, tenant: str) -> NewSource:
    """The columns of a new source's row: all of the source's but the ones only a sync or a lease sets."""
    return NewSource(
        tenant_id=tenant,
        id=row.id,
        team_id=row.team_id,
        type=row.type,
        name=row.name,
        collection=row.collection,
        owner=row.owner,
        sensitivity=row.sensitivity,
        status=row.status,
        tags=row.tags,
        file_ids=row.file_ids,
        file_names=row.file_names,
        created_by=row.created_by,
        created_at=row.created_at,
        last_sync_at=row.last_sync_at,
        last_run_status=row.last_run_status,
        config=row.config,
        settings=row.settings,
    )


def pieces(  # noqa: PLR0917 - each argument a different part of the piece rows
    tenant: str, item_id: str, version: int, title: str, result: SplitResult, metadata: dict[str, str]
) -> list[PieceWrite]:
    """A split as the rows kb_chunks and kb_units hold: each piece once, with the units it is searched as (its own
    text with its context header, its children, its questions), so a match on any unit cites the piece."""
    rows: list[PieceWrite] = []
    ids = [new_id("chk") for _ in result.chunks]
    units: dict[int, list[UnitWrite]] = {}
    for unit in result.index_units():
        chunk = result.chunks[unit.chunk_index]
        heading = " ".join(p for p in (title, " > ".join(chunk.section_path)) if p)
        mine = units.setdefault(unit.chunk_index, [])
        mine.append(
            UnitWrite(
                tenant_id=tenant,
                id=new_id("unt"),
                chunk_id=ids[unit.chunk_index],
                item_id=item_id,
                kind=unit.kind,
                position=len(mine),
                heading=heading[:800],
                text=unit.indexed_text,
            )
        )
    for n, c in enumerate(result.chunks):
        rows.append(
            PieceWrite(
                tenant_id=tenant,
                id=ids[n],
                item_id=item_id,
                version=version,
                position=n,
                title=title,
                section=" > ".join(c.section_path),
                page=c.page,
                tokens=c.tokens,
                text=c.text,
                metadata={**metadata, **c.metadata} or None,
                units=units.get(c.index, []),
            )
        )
    return rows


def run_row(run: RunWrite) -> RunRow:
    """A run this request wrote, as the store reads it back: who started it and its tenant are not shown."""
    return RunRow.model_validate({k: v for k, v in run.items() if k in RunRow.model_fields})


def _run(r: RunRow) -> RunView:
    return {
        "id": r.id,
        "sourceId": r.source_id,
        "trigger": r.trigger,
        "startedAt": _iso(r.started_at),
        "durationSec": r.duration_sec,
        "status": r.status,
        "counts": r.counts,
        "phases": [],
        "errors": r.errors,
        "log": r.log,
        **(RunParts(finishedAt=_iso(r.finished_at)) if r.finished_at else RunParts()),
        **(RunParts(cancelledBy=r.cancelled_by) if r.cancelled_by else RunParts()),
    }


def health_of(s: SourceRow) -> SourceHealth:
    """A source's health in one place: never synced, healthy, failing (since when, for how many days) or waiting for
    its connection to be signed in again."""
    cfg = dict(s.config or {})
    since: datetime | None = s.failing_since
    good: datetime | None = s.last_good_sync_at
    reconnect = cfg.get("paused") == "needs_reconnect"
    state = "needs_reconnect" if reconnect else "failing" if since else "healthy" if good or s.last_sync_at else "never"
    return SourceHealth.model_validate(
        {
            "state": state,
            **({"lastGoodSyncAt": _iso(good)} if good else {}),
            **({"failingSince": _iso(since)} if since else {}),
            "daysFailing": (datetime.now(UTC) - since).days if since else 0,
            "failedRuns": int(s.failures_in_row or 0),
            "tombstoned": len(json_object(cfg.get("tombstones"))),
        }
    )


class Uploaded(TypedDict):
    """A file kb-service stored and added to a source, as `upload` answers it."""

    fileId: str
    name: str
    mime: str
    size: int
    digest: str
    deduplicated: bool


class KindDefaults(TypedDict):
    """What a new source of a kind starts with, as the source kinds list shows it."""

    defaults: Json


def kind_defaults(kind: str, ocr: str, *, plugin_schedule: dict[str, JsonValue] | None = None) -> KindDefaults:
    """A new source's settings for its kind and its schedule, as create applies them."""
    schedule = WEB_SCHEDULE if kind == "web" else plugin_schedule or {"kind": "manual"}
    return {"defaults": {**wire(defaults(kind, ocr=ocr)), "schedule": schedule}}


def scope_summary(s: SourceRow) -> str:
    """What a source takes in, in a few words: a site's start address, or a plugin source's name, or its files."""
    if s.type in WRITTEN_TYPES:
        return f"{len(s.file_ids)} {'pages' if s.type == 'text' else 'pushed items'}"
    if s.type != "tool":
        n = len(s.file_ids)
        return f"{n} uploaded file" if n == 1 else f"{n} uploaded files"
    cfg = dict(s.config or {})
    values = json_object(cfg.get("values"))
    start = cast(list[Any], values.get("start") or [])
    if start:
        first = str(start[0]).split("://", 1)[-1].rstrip("/")
        return first if len(start) == 1 else f"{first} and {len(start) - 1} more"
    return f"{cfg.get('plugin')} {cfg.get('source')}"


# A source's kind in words, when its plugin's own title for it is not kept (a source made before titles were).
KIND_LABEL = {"file": "Files", "text": "Typed text", "push": "Pushed by API", "web": "Website", "tool": "App source"}


def kind_label(s: SourceRow) -> str:
    """What the source is, as the Add source dialog named it: Files, or the plugin's title for the source."""
    title = dict(s.config or {}).get("title")
    return str(title) if s.type == "tool" and title else KIND_LABEL.get(kind_of(s), str(s.type))


def ai_steps_waiting(settings: IngestSettings) -> list[str]:
    """The AI steps chosen and not yet approved by the knowledge owner; syncs run without them until then."""
    return [
        step for step in settings.strategies if step in AI_STEPS and not ai_step_allowed(settings, step, preview=False)
    ]


def written_bytes(i: ItemInput, title: str) -> tuple[bytes, str]:
    """The bytes and mime of an item written through the API: its `text` (Markdown by default, headed by its title) or
    its base64 `content`, one of the two."""
    text, content = i.get("text"), i.get("content")
    if (text is None) == (content is None):
        raise ValidationFailed("Send the item's text or its base64 content, one of the two.")
    if content is not None:
        mime = str(i.get("mime") or "")
        if not mime:
            raise ValidationFailed("Name the content's type in mime, such as application/pdf.")
        try:
            data = base64.b64decode(str(content), validate=True)
        except (ValueError, binascii.Error) as e:
            raise ValidationFailed("The content is not base64.") from e
        if not data:
            raise ValidationFailed("The content is empty.")
        return data, mime
    mime = str(i.get("mime") or "text/markdown")
    if mime not in WRITTEN_TEXT_MIMES:
        raise ValidationFailed(f"Text is one of {', '.join(WRITTEN_TEXT_MIMES)}; send other files as content.")
    body = str(text).strip()
    if not body:
        raise ValidationFailed("Write the item's text.")
    if title and mime == "text/markdown" and not body.startswith("# "):
        body = f"# {title}\n\n{body}"
    return f"{body}\n".encode(), mime


def kind_of(s: SourceRow) -> str:
    """The kind a source's defaults are chosen by: a plugin source whose items are one website's pages is `web`."""
    if s.type == "tool" and dict(s.config or {}).get("site"):
        return "web"
    return str(s.type)


def repeats_of(s: SourceRow) -> list[str]:
    """The lines last found repeated across the source's pages."""
    found = cast(list[Any], dict(s.config or {}).get("repeats") or [])
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


# Items an AI estimate splits, and the output tokens a questions call writes (a few short questions, up to its cap).
ESTIMATE_SAMPLE = 20
OUTPUT_LOW, OUTPUT_HIGH = 60, 120


class CountingModel:
    """A model client for an estimate: counts each call and its prompt's tokens, and answers with nothing."""

    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0

    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str:
        self.calls += 1
        self.input_tokens += approx_tokens(prompt)
        return '{"questions": []}'


# FAQ units follow a piece's own units, so their positions never meet.
FAQ_POSITION = 1_000
# A draft a person may still decide: waiting, or approved before its section changed.


# A change's origin as stored, and as the API names it.
SHOWN_ORIGIN = {"sync": "source_sync", "faq": "generated_faq"}
CHANGE_ORIGINS = {shown: stored for stored, shown in SHOWN_ORIGIN.items()}


def _draft_out(ch: ChangeRow, s: SourceRow | None, kbs: list[KbRef]) -> ChangeCore:
    """An FAQ draft as the Changes queue shows it: the pair, the passage it quotes beside it, and its review state."""
    detail = detail_of(ch)
    return {
        "id": ch.id,
        "summary": str(detail.get("question") or ""),
        "origin": SHOWN_ORIGIN["faq"],
        "proposedBy": "FAQ drafts",
        "rationale": f"Drafted from {ch.title}, {ch.section or 'its text'}.",
        "documentId": ch.item_id,
        "documentTitle": ch.title,
        "sourceId": ch.source_id,
        "sourceName": s.name if s else "",
        "section": ch.section,
        "kbs": kbs,
        "fromVersion": f"v{ch.from_version}",
        "toVersion": f"v{ch.to_version}",
        "before": str(detail.get("quote") or ""),
        "after": ch.after,
        "trust": "source_changed" if ch.status == "source_changed" else "draft",
        "citedBy": [],
        "owner": s.owner if s else "",
        "canDecide": ch.status in DECIDABLE,
        "status": ch.status,
        "createdAt": _iso(ch.changed_at),
        "decidedAt": _iso(ch.decided_at) if ch.decided_at else None,
        "decidedBy": ch.decided_by,
        "decisionReason": ch.decision_reason,
        "faq": {
            "question": str(detail.get("question") or ""),
            "answer": str(detail.get("answer") or ""),
            "quote": str(detail.get("quote") or ""),
            "sectionPath": [*path] if isinstance(path := detail.get("sectionPath"), list) else [],
            "addsWords": adds_words(str(detail.get("answer") or ""), str(detail.get("quote") or "")),
        },
    }


_COMMON = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "has", "have", "how", "i",
    "if", "in", "is", "it", "its", "my", "of", "on", "or", "our", "so", "that", "the", "their", "there", "this",
    "to", "was", "we", "what", "when", "where", "which", "who", "will", "with", "you", "your", "yes", "no", "not",
    "any", "all", "may",
))  # fmt: skip


def adds_words(answer: str, passage: str) -> list[str]:
    """Words of an answer its passage never uses (common words aside): a sign the answer says more than its source."""
    words = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", answer.lower())
    held = set(re.findall(r"[a-z0-9]+(?:'[a-z]+)?", passage.lower()))
    return list(dict.fromkeys(w for w in words if w not in held and w not in _COMMON and len(w) > 2))


def detail_of(change: ChangeRow) -> dict[str, JsonValue]:
    """A draft's detail (question, answer, quote, section); empty for a sync's change."""
    return change.detail or {}


def ai_steps_on(settings: IngestSettings) -> bool:
    """Whether the split will ask a model: an AI step chosen and approved."""
    return any(step in AI_STEPS and ai_step_allowed(settings, step, preview=False) for step in settings.strategies)


def _stored_tuple(value: JsonValue) -> tuple[str, ...]:
    """A stored scope list as `tuple(value or ())` reads it: the elements as stored (a string as its letters, a
    number raising), so a scope never reads wider or narrower than it did."""
    return tuple(cast("Iterable[str]", value or ()))


def scope_of(r: Retrieval) -> Scope:
    """A base's scope from its retrieval settings: the pieces its search may return."""
    held = r.get("filters") or {}
    # dict() of a list of pairs, a string or a number reads, or raises, as it did before saves were checked.
    filters = dict(held) if isinstance(held, dict) else dict(cast("Iterable[tuple[str, JsonValue]]", held))
    # The filter decides what a search may return: a malformed one fails the search rather than widening it.
    listed = filters.get("conditions")
    conditions = [
        narrow.an_object(c, "filter condition") for c in (narrow.a_list(listed, "conditions") if listed else [])
    ]
    return Scope(
        collections=_stored_tuple(r.get("scopeCollections")),
        source_ids=_stored_tuple(r.get("scopeSourceIds")),
        tags_include=_stored_tuple(r.get("tagsInclude")),
        tags_exclude=_stored_tuple(r.get("tagsExclude")),
        include_untagged=bool(r.get("includeUntagged", True)),
        match=str(filters.get("match") or "all"),
        conditions=tuple((str(c["key"]), str(c["op"]), str(c.get("value") or "")) for c in conditions),
    )


def search_settings(bases: list[BaseRow], *, limit: int | None = None, collection: str | None = None) -> Search:
    """One search over several bases: the lanes any of them asks for, the lowest threshold, the mean weight toward
    meaning and the largest piece limit, so no base gets less than it asks; `limit` caps the pieces further. Scopes do
    not merge: each base keeps its own, and `collection` narrows them all."""
    if not bases:
        return Search(limit=limit or int(DEFAULT_RETRIEVAL["chunkLimit"]), collection=collection)
    settings = [RETRIEVAL({**narrow.an_object(DEFAULT_RETRIEVAL, "retrieval"), **b.retrieval}) for b in bases]
    lanes: tuple[Lane, ...] = tuple(dict.fromkeys(lane for r in settings for lane in lanes_for(str(r["searchMode"]))))
    most = max(int(r["chunkLimit"]) for r in settings)
    return Search(
        lanes=lanes,
        threshold=min(float(r["threshold"]) for r in settings),
        meaning_threshold=min(float(r["meaningThreshold"]) for r in settings),
        weight=sum(float(r["hybridWeight"]) for r in settings) / len(settings),
        limit=min(most, limit) if limit else most,
        scopes={b.id: scope_of(r) for b, r in zip(bases, settings, strict=True)},
        collection=collection,
    )


def found_out(found: Found) -> SearchOut:
    """The search reply without `answers`, which only the search route adds; dumped with `exclude_unset`, so a key
    the search did not fill (a rewrite or rerank that was not asked for) is left out as before."""
    return SearchOut.model_validate(
        {
            "passages": [passage_out(p) for p in found.passages],
            "lanes": found.lanes_out(),
            "cost": {"embeddingTokens": found.embedding_tokens},
            **({"rewrite": found.rewrite} if found.rewrite is not None else {}),
            **({"rerank": found.rerank} if found.rerank is not None else {}),
        }
    )


def checked_retrieval(r: Json) -> Json:
    """A base's retrieval settings as saved: the steps around the search refused when they are not ones it runs."""
    if r.get("rewrite") not in REWRITE_MODES:
        raise ValidationFailed(
            f"Rewrite is one of {', '.join(REWRITE_MODES)}; expanding a question into several is not built.",
            code="invalid_retrieval",
        )
    if not isinstance(r.get("rerank"), bool):
        raise ValidationFailed("Rerank is on or off.", code="invalid_retrieval")
    if len(str(r.get("rewriteInstructions") or "")) > 1000:
        raise ValidationFailed("Keep the rewrite instruction under 1,000 characters.", code="invalid_retrieval")
    return r


class ReviewState(TypedDict):
    freshness: str
    reviewBy: str


class CopyView(TypedDict):
    title: str
    sourceName: str


class ItemParts(TypedDict, total=False):
    """The keys an item's reply carries only when they hold something."""

    url: str
    processedAt: str | None
    errorClass: str
    error: str | None
    warning: str
    duplicateOf: str
    duplicateCopy: CopyView
    folder: str
    pageCount: int


class ItemView(ItemParts):
    """An item as the API sends it, keys in the order sent (a TypedDict, so the reply is the dict built): `Item` in
    schemas.py documents the same fields in another order, and reordering it would change openapi.json."""

    id: str
    sourceId: str
    externalId: str
    title: str
    mimeType: str
    path: str
    modifiedAt: str | None
    sizeBytes: int
    status: str
    chunkCount: int
    tags: list[str]
    metadata: Json
    acl: list[str]
    owner: str
    version: str
    effectiveDate: str
    freshness: str
    reviewBy: str
    sensitivity: str
    collection: str
    verified: bool
    queries30d: int
    fileId: str
    digest: str
    family: str
    versionStatus: str


class UsedBy(TypedDict):
    agentNames: list[str]
    agentsElsewhere: int
    agentsKnown: bool


class ItemCounts(TypedDict):
    itemsIndexed: int
    itemsFailed: int
    itemsPending: int


class SourceCounts(TypedDict, total=False):
    """What a base's reply reads of one source: its documents indexed and failed, its chunks, when it last synced and
    how fresh it is. A source with no row reads as {}: no documents and never synced."""

    indexed: int
    failed: int
    chunks: int
    synced: datetime | None
    freshness: str


class Rights(TypedDict):
    canPublish: bool
    canEdit: bool
    canDelete: bool


class EmbeddingView(TypedDict):
    model: str
    width: int
    embedded: int
    units: int


class FileConfig(TypedDict):
    fileIds: list[str]


class SourceParts(TypedDict, total=False):
    """The keys a source's reply carries only when they hold something."""

    nextSyncAt: str | None
    lastSyncAt: str | None
    lastRunStatus: str


class SourceView(SourceParts, ItemCounts):
    """A source as the API sends it, keys in the order sent; `Source` in schemas.py documents the same fields in
    another order. Its settings sections are passed on as `wire` writes them."""

    id: str
    type: str
    name: str
    kind: str
    kindLabel: str
    scopeSummary: str
    # A plugin source's settings as stored (any JSON a plugin accepts), or a file source's files.
    config: Json | FileConfig
    parsing: JsonValue
    cleaning: JsonValue
    ingest: JsonValue
    rules: JsonValue
    metadataMapping: JsonValue
    aiCeiling: JsonValue
    aiStepsWaiting: list[str]
    waitingHosts: list[JsonValue]
    tags: list[str]
    titleFrom: str
    permissions: Json
    schedule: Json
    health: Json
    deletedAtSource: str
    staleAfterDays: Number
    notifyOnFailure: bool
    sensitivity: str
    collection: str
    owner: str
    status: str
    usedByKbIds: list[str]
    createdAt: str | None


class SourceLink(TypedDict):
    sourceId: str
    itemsContributed: int
    rules: list[JsonValue]


class BaseAccess(TypedDict):
    members: Json
    anyApiKey: bool
    mcp: Mcp
    publicLink: Json
    documentPermissions: str


class BaseParts(TypedDict, total=False):
    lastRefreshedAt: str | None
    lastSyncAt: str | None


class BaseView(BaseParts):
    """A knowledge base as the API sends it, keys in the order sent; `KnowledgeBase` in schemas.py documents the same
    fields in another order. The settings sections are the ones `sections_of` builds, in its order."""

    id: str
    name: str
    slug: str
    templateId: str | None
    protection: str | None
    description: str
    color: str
    owner: str
    sources: list[SourceLink]
    collections: list[str]
    precedence: list[dict[str, str]]
    metadataProfile: Json
    retrieval: Json
    answer: Answer
    sync: Sync
    sourceDefaults: SourceSplit
    access: BaseAccess
    automation: str
    stats: Json
    health: str
    healthReasons: list[str]
    jobs: list[Json]
    createdAt: str | None


class BaseRowView(BaseView, UsedBy):
    """A base as the list sends it: with its sources' names and the agents citing it."""

    sourceNames: list[str]


class AttachedSource(SourceLink):
    source: SourceView
    running: bool


class DetailParts(TypedDict, total=False):
    embedding: EmbeddingView


class BaseDetailView(BaseRowView, Rights, DetailParts):
    attached: list[AttachedSource]
    metadataKeys: list[str]
    suggestedQuestions: list[str]
    heldCount: int


class RunParts(TypedDict, total=False):
    finishedAt: str | None
    cancelledBy: str


class RunView(RunParts):
    """A sync run as the API sends it, keys in the order sent. Errors and log entries are passed on as the run row
    holds them: a stored error may carry a null errorClass or message, or keys `RunError` does not name."""

    id: str
    sourceId: str
    trigger: str
    startedAt: str | None
    durationSec: float
    status: str
    counts: dict[str, int]
    phases: list[JsonValue]
    errors: list[JsonValue]
    log: list[JsonValue]


class Provisioned(TypedDict, total=False):
    """The fields of a create only the provisioning service sets."""

    templateId: str | None
    protection: str | None


class BaseInput(Provisioned, total=False):
    """A new knowledge base as `KnowledgeBaseIn` dumps it by alias, or as the seed sends it."""

    id: str | None
    name: str
    owner: str | None
    description: str
    color: str
    sourceIds: list[str]
    preset: str
    collections: list[str]
    retrieval: Json | None
    answer: Json | None
    sync: Json | None
    access: Json | None
    sourceDefaults: Json | None


class SourceInput(TypedDict, total=False):
    """A new source as `SourceIn` dumps it by alias, or as the seed and the pages and documents sources send it."""

    type: str
    name: str
    collection: str
    owner: str | None
    sensitivity: str
    status: str | None
    tags: list[str]
    fileIds: list[str]
    kbIds: list[str]
    sync: bool
    config: Json | None
    schedule: Json | None
    parsing: Json | None
    cleaning: Json | None
    ingest: Json | None
    rules: list[Json] | None
    metadataMapping: list[Json] | None
    aiCeiling: float | None


class SourcePatchInput(TypedDict, total=False):
    """A source's patch as `SourcePatch` dumps it by alias with no nulls."""

    name: str
    values: Json
    collection: str
    owner: str
    sensitivity: str
    tags: list[str]
    schedule: Json
    parsing: Json
    cleaning: Json
    ingest: Json
    rules: list[Json]
    metadataMapping: list[Json]
    aiCeiling: float


class ItemInput(TypedDict, total=False):
    """An item written through the API, as `WrittenItemIn` dumps it with no nulls."""

    name: str
    title: str
    text: str
    content: str
    mime: str
    url: str


class PluginSourceView(TypedDict):
    """A source made from a plugin's knowledge source, as `plugin_sources` sends it."""

    id: str
    name: str
    source: str
    kbIds: list[str]


class ReaderView(TypedDict):
    id: str
    name: str
    slug: str
    color: str
    health: str


class Governance(TypedDict):
    excluded: int
    held: int
    duplicates: int
    superseded: int


class LastRun(TypedDict, total=False):
    lastRunDurationSec: float


class SourceDetailView(SourceView, Rights, LastRun):
    """A source's detail page, keys in the order sent; `SourceDetail` in schemas.py documents the same fields."""

    readers: list[ReaderView]
    recentRuns: list[RunView]
    running: RunView | None
    errorGroups: list[Json]
    itemCount: int
    reindexNeeded: bool
    requiredMetadata: list[str]
    governance: Governance


class SourceRebuilt(SourceView):
    """A source after a settings change, with the rebuild the change started (None when it needs none)."""

    rebuild: RunView | None


class AppKindParts(TypedDict, total=False):
    """The keys a kind read from a team's app carries; a built-in kind has none of them."""

    plugin: str
    source: str
    site: bool
    files: bool
    connectionId: str | None
    needsConnection: bool
    connected: bool
    canCreate: bool
    cannotCreateCode: str
    cannotCreateBecause: str
    previews: bool
    pickers: bool
    inputs: dict[str, Json]


class SourceKindView(KindDefaults, AppKindParts):
    """One kind Add source lists, keys in the order sent; `SourceKind` in schemas.py documents the same fields."""

    type: str
    group: str
    title: str
    kind: str


class KbRef(TypedDict):
    id: str
    name: str


class FaqView(TypedDict):
    question: str
    answer: str
    quote: str
    sectionPath: list[JsonValue]
    addsWords: list[str]


class Decided(TypedDict, total=False):
    """The keys a change carries once decided (an FAQ draft carries them always, null until then), and a draft's
    pair."""

    decidedAt: str | None
    decidedBy: str | None
    decisionReason: str | None
    faq: FaqView


class ChangeCore(Decided):
    """A change as `_draft_out` builds it, before its source's review state is added."""

    id: str
    summary: str
    origin: str
    proposedBy: str
    rationale: str
    documentId: str
    documentTitle: str
    sourceId: str
    sourceName: str
    section: str
    kbs: list[KbRef]
    fromVersion: str
    toVersion: str
    before: str
    after: str
    trust: str
    citedBy: list[Json]
    owner: str
    canDecide: bool
    status: str
    createdAt: str | None


class ChangeView(ChangeCore, ReviewState):
    """A change as the Changes queue sends it; `KnowledgeChange` in schemas.py documents the same fields in another
    order."""


class ChangeListView(TypedDict):
    data: list[ChangeView]
    pagination: PageJSON
    facets: dict[str, dict[str, int]]
    viewCounts: dict[str, int]


class CitationParts(TypedDict, total=False):
    page: int


class CitationView(CitationParts):
    n: int
    documentId: str
    title: str
    section: str
    version: str
    snippet: str


class ChunkView(TypedDict):
    chunkId: str
    documentId: str
    documentTitle: str
    sourceName: str
    score: float
    lanes: dict[str, float]
    location: str
    text: str
    rejected: bool
    version: str


class FoundParts(TypedDict, total=False):
    """`SearchOut` dumped with `exclude_unset`: the passages, lanes and cost, and a rewrite or rerank when asked."""

    passages: list[Json]
    lanes: Json
    cost: Json
    rewrite: Json | None
    rerank: Json | None
    noAnswer: bool


class QueryView(FoundParts):
    """The Playground's answer, keys in the order sent; `PlaygroundAnswer` in schemas.py documents the same fields."""

    id: str
    question: str
    matchers: list[str]
    answer: str
    citations: list[CitationView]
    chunks: list[ChunkView]
    retrievalMs: int
    synthesisMs: int
    shape: str


class TokenRange(TypedDict):
    low: int
    high: int


class AiEstimateView(TypedDict):
    steps: list[str]
    model: str
    sampledItems: int
    totalItems: int
    calls: int
    inputTokens: int
    outputTokens: TokenRange
    basis: str


class WrittenItemView(TypedDict):
    outcome: str
    item: ItemView


class AddedDocumentsView(TypedDict):
    sourceId: str
    files: list[dict[str, str]]
    run: RunView


class SettingsUsed(TypedDict):
    preset: str
    strategies: list[IngestStrategy]
    indexedWith: JsonValue
    current: bool


class SearchedAs(TypedDict):
    kind: str
    text: str


class ChunkDetail(CitationParts):
    index: int
    tokens: int
    location: str
    kind: str
    text: str
    units: list[SearchedAs]
    metadata: Mapping[str, JsonValue]


class Allowed(TypedDict, total=False):
    allowed: list[JsonValue]


class VersionDetail(Allowed):
    itemId: str
    title: str
    version: str
    effectiveDate: str
    status: str
    digest: str
    sourceName: str


class ItemDetail(TypedDict):
    content: str
    chunks: list[ChunkDetail]
    revisions: list[Json]
    versions: list[VersionDetail]


class ItemDetailView(ItemView):
    """An item's page, keys in the order sent; `ItemWithDetail` in schemas.py documents the same fields."""

    reading: Json | None
    settingsUsed: SettingsUsed
    sourceName: str
    sourceType: str
    detail: ItemDetail


class HeldVersion(TypedDict):
    """A version a sync built and held for review: the rows approving it writes."""

    item: ItemWrite
    version: VersionWrite
    chunks: list[PieceWrite]


HELD_VERSION = TypeAdapter(HeldVersion)


def _json_safe(value: object) -> JsonValue:
    """A held version as JSON: datetimes kept as {"$at": iso} so they come back as datetimes."""
    if isinstance(value, datetime):
        return {"$at": value.isoformat()}
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in cast(dict[object, object], value).items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in cast(list[object], value)]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"a held version holds no {type(value).__name__}")


def _from_json_safe(value: JsonValue) -> object:
    if isinstance(value, dict):
        if set(value) == {"$at"}:
            return datetime.fromisoformat(str(value["$at"]))
        return {k: _from_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_json_safe(v) for v in value]
    return value


def _keys(model: type[BaseModel]) -> set[str]:
    return {f.alias or name for name, f in model.model_fields.items()}


def tool_name(slug: str) -> str:
    """The MCP tool a base is offered as until someone names it: search_<slug>, cut to the 64 characters allowed."""
    return f"search_{slug}"[:64].rstrip("_") or "search_knowledge"


def settings_of(b: BaseRow) -> Sections:
    """Every settings section of a base as it applies (`sections_of`)."""
    return sections_of(b.slug, b.retrieval, b.settings)


def sections_of(slug: str, retrieval: Json, saved: Json | None) -> Sections:
    """Every settings section of a base as it applies: the defaults under what the base stored, with keys it no longer
    keeps left out. A base saved before the answer section existed keeps the answer shape and no-answer message it held
    in its retrieval settings."""
    held = dict(retrieval)
    out: Json = {
        "retrieval": {
            k: v
            for k, v in {**narrow.an_object(DEFAULT_RETRIEVAL, "retrieval"), **held}.items()
            if k in _keys(RetrievalSettings)
        }
    }
    earlier: Json = {}
    if held.get("answerShape") == "chunks":
        earlier["shape"] = "chunks"
    if held.get("noAnswerMessage"):
        earlier["noAnswerMessage"] = str(held["noAnswerMessage"])
    for name, default in narrow.an_object(DEFAULT_SETTINGS, "settings").items():
        given = {**(earlier if name == "answer" else {}), **narrow.an_object((saved or {}).get(name) or {}, name)}
        out[name] = {
            k: v for k, v in {**narrow.an_object(default, name), **given}.items() if k in _keys(SECTIONS[name])
        }
    access = narrow.an_object(out["access"], "access")
    out["access"] = {"mcp": {"toolName": tool_name(slug), **dict(narrow.an_object(access.get("mcp") or {}, "mcp"))}}
    return SECTIONS_READ(out)


def settled(current: Sections, given: Mapping[str, JsonValue]) -> Sections:
    """The sections after a change: each section sent merges over the stored one (the keys sent change, the rest stay)
    and is checked whole. A key a section does not keep, or a value out of range, is 400 `invalid_settings`."""
    now = narrow.an_object(current, "settings")
    out = dict(now)
    for name, model in SECTIONS.items():
        sent = given.get(name)
        if sent is None:
            continue
        patch = json_object(sent)
        if not isinstance(sent, dict):
            raise ValidationFailed(f"{name} is an object of settings.", code="invalid_settings")
        merged: Json = {**narrow.an_object(now[name], name), **patch}
        if name == "access" and isinstance(patch.get("mcp"), dict):
            merged["mcp"] = {**narrow.an_object(current["access"]["mcp"], "mcp"), **json_object(patch["mcp"])}
        if name == "retrieval":
            checked_retrieval(merged)
        try:
            out[name] = model.model_validate(merged).model_dump(by_alias=True, mode="json")
        except ValidationError as e:
            raise ValidationFailed(_refusal(name, e), code="invalid_settings") from e
        if name == "sourceDefaults":
            try:
                validate_settings(IngestSettings.model_validate(out[name]))
            except InvalidIngestError as e:
                raise ValidationFailed(str(e), code="invalid_settings") from e
    return SECTIONS_READ(out)


def _refusal(section: str, e: ValidationError) -> str:
    first = e.errors()[0]
    where = ".".join(str(p) for p in first["loc"])
    if first["type"] == "extra_forbidden":
        return f"A knowledge base's {section} settings have no {where}."
    return f"{section}.{where}: {first['msg']}"


def passage_out(p: Passage) -> PassageOut:
    return PassageOut.model_validate(
        {
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
            **({"reranked": p.reranked} if p.reranked is not None else {}),
        }
    )
