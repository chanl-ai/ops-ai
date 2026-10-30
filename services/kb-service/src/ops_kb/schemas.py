"""kb-service's request and response models, matching apps/console/src/lib/types/knowledge.ts. Nested settings the
console owns the shape of (retrieval, access, ingest) are documented as objects; their defaults live in service.py."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_service_kit.http import ListResult, Out

Json = dict[str, Any]


class In(BaseModel):
    # The console sends its whole input type; fields this slice does not run are accepted and ignored.
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


class KnowledgeBaseIn(In):
    # A caller-chosen id, for knowledge bases that agents were granted before they moved here; kb-service makes one.
    id: str | None = Field(default=None, pattern=r"^kb_[a-z0-9_]{1,60}$")
    name: str
    # Set by the provisioning service only (c-180).
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None
    owner: str | None = None
    description: str = ""
    color: str = "blue"
    source_ids: list[str] = []
    preset: Literal["balanced", "precise", "raw"] = "balanced"
    collections: list[str] = []


class KnowledgeBasePatch(In):
    # Set by the provisioning service only (c-180).
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None
    name: str | None = None
    owner: str | None = None
    description: str | None = None
    color: str | None = None
    collections: list[str] | None = None
    retrieval: Json | None = None


class AttachIn(In):
    source_ids: list[str]


class SourceIn(In):
    type: str
    name: str
    collection: str = ""
    owner: str | None = None
    sensitivity: str = "internal"
    status: str | None = None
    tags: list[str] = []
    file_ids: list[str] = []
    kb_ids: list[str] = []
    sync: bool = False
    # A "tool" source's plugin and source names (c-564): {"plugin": "opsai.salesforce", "source": "articles"}. Any
    # values: the console's Add source sends its whole draft config for every type, and only a tool source reads it.
    config: dict[str, Any] | None = None


class KbSourceLink(Out):
    source_id: str
    items_contributed: int
    rules: list[Json]


class KnowledgeBase(Out):
    id: str
    name: str
    slug: str
    # From the provisioning service (c-180): the template it was made from, and `system` or `managed`; null otherwise.
    template_id: str | None = None
    protection: Literal["system", "managed"] | None = None
    description: str
    color: str
    owner: str
    sources: list[KbSourceLink]
    collections: list[str]
    precedence: list[Json]
    metadata_profile: Json
    retrieval: Json
    access: Json
    automation: str
    stats: Json
    health: str
    health_reasons: list[str]
    last_refreshed_at: str | None = None
    indexing: Json | None = None
    jobs: list[Json]
    created_at: str


class KnowledgeBaseRow(KnowledgeBase):
    source_names: list[str]
    # Agents of the caller's team citing the base; agents of other teams are counted; `agentsKnown` is false when
    # agents-service could not say.
    agent_names: list[str]
    agents_elsewhere: int = 0
    agents_known: bool = True


class Source(Out):
    id: str
    type: str
    name: str
    scope_summary: str
    config: Json
    parsing: Json
    ingest: Json
    rules: list[Json]
    metadata_mapping: list[Json]
    tags: list[str]
    title_from: str
    permissions: Json
    schedule: Json
    deleted_at_source: str
    stale_after_days: int
    notify_on_failure: bool
    sensitivity: str
    collection: str
    owner: str
    status: str
    items_indexed: int
    items_failed: int
    items_pending: int
    last_sync_at: str | None = None
    last_run_status: str | None = None
    used_by_kb_ids: list[str]
    created_at: str


class NamedRef(Out):
    id: str
    name: str


class SourceRow(Source):
    used_by: list[NamedRef]
    running: bool


class KbSourceView(KbSourceLink):
    source: Source


class KnowledgeBaseDetail(KnowledgeBaseRow):
    attached: list[KbSourceView]
    metadata_keys: list[str]
    suggested_questions: list[str]
    held_count: int
    # What the caller may do with it (c-216), from the write routes' own check.
    can_edit: bool | None = None
    can_delete: bool | None = None
    can_publish: bool | None = None


class Reader(Out):
    id: str
    name: str
    slug: str
    color: str
    health: str


class SourceDetail(Source):
    readers: list[Reader]
    last_run_duration_sec: float | None = None
    running: Json | None = None
    recent_runs: list[Json]
    error_groups: list[Json]
    item_count: int
    reindex_needed: bool
    required_metadata: list[str]
    governance: Json
    ai_steps_waiting: list[str]
    # What the caller may do with it (c-216), from the write routes' own check.
    can_edit: bool | None = None
    can_delete: bool | None = None
    can_publish: bool | None = None


class SyncRun(Out):
    id: str
    source_id: str
    trigger: str
    started_at: str
    duration_sec: float
    status: str
    counts: dict[str, int]
    phases: list[Json]
    errors: list[Json]
    log: list[str]


class Item(Out):
    id: str
    source_id: str
    external_id: str
    title: str
    mime_type: str
    path: str
    modified_at: str
    processed_at: str | None = None
    size_bytes: int
    status: str
    error_class: str | None = None
    error: str | None = None
    warning: str | None = None
    chunk_count: int
    tags: list[str]
    metadata: dict[str, str]
    acl: list[str]
    owner: str
    version: str
    effective_date: str
    review_by: str
    sensitivity: str
    collection: str
    verified: bool
    queries30d: int = Field(alias="queries30d")
    page_count: int | None = None
    file_id: str | None = None
    digest: str
    family: str
    version_status: str


class DocumentRow(Item):
    source_name: str
    freshness: str


class ItemWithDetail(Item):
    source_name: str
    source_type: str
    detail: Json


class QueryIn(In):
    question: str


class PageIn(In):
    title: str = Field(max_length=200)
    text: str = Field(max_length=100_000)


class SearchIn(In):
    kb_ids: list[str]
    question: str
    limit: int = 8


class PassageOut(Out):
    kb_id: str
    item_id: str
    version: str
    title: str
    section: str
    page: int | None = None
    snippet: str
    text: str
    score: float


class SearchOut(Out):
    passages: list[PassageOut]


class PlaygroundAnswer(Out):
    id: str
    question: str
    matchers: list[str]
    answer: str
    citations: list[Json]
    chunks: list[Json]
    no_answer: bool | None = None
    retrieval_ms: int
    synthesis_ms: int
    shape: str


class KnowledgeChange(Out):
    id: str
    summary: str
    origin: str
    proposed_by: str
    rationale: str
    document_id: str
    document_title: str
    source_id: str
    source_name: str
    section: str
    kbs: list[NamedRef]
    from_version: str
    to_version: str
    before: str
    after: str
    trust: str
    freshness: str
    review_by: str
    cited_by: list[Json]
    owner: str
    can_decide: bool
    status: str
    created_at: str
    decided_at: str | None = None
    decided_by: str | None = None


class ChangeViewCounts(Out):
    mine: int
    open: int
    conflicts: int
    resolved: int


class ChangeList(ListResult[KnowledgeChange]):
    view_counts: ChangeViewCounts


class SyncIn(BaseModel):
    """The console's SyncOptions. Unknown fields are refused rather than ignored, so a caller never believes an option
    it sent was honoured."""

    model_config = ConfigDict(extra="forbid")
    full: bool = False
    retry: bool = False


class SourcePatch(In):
    name: str | None = None
    collection: str | None = None
    owner: str | None = None
    sensitivity: str | None = None
    tags: list[str] | None = None


class FileIdsIn(In):
    file_ids: list[str] = Field(min_length=1, max_length=50)


class AddedFile(Out):
    file_id: str
    name: str


class AddedDocuments(Out):
    source_id: str
    files: list[AddedFile]
    run: SyncRun


class VerifyIn(In):
    verified: bool


class OwnerIn(In):
    owner: str


class Lookups(Out):
    owners: list[str]
    tags: list[str]
    collections: list[str]
