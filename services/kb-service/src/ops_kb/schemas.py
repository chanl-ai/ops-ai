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
    # Set by the provisioning service only.
    template_id: str | None = Field(default=None, min_length=1, max_length=120)
    protection: Literal["system", "managed"] | None = None
    owner: str | None = None
    description: str = ""
    color: str = "blue"
    source_ids: list[str] = []
    preset: Literal["balanced", "precise", "raw"] = "balanced"
    collections: list[str] = []


class KnowledgeBasePatch(In):
    # Set by the provisioning service only.
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
    # A "tool" source's plugin and source names: {"plugin": "opsai.salesforce", "source": "articles"}. Any
    # values: the console's Add source sends its whole draft config for every type, and only a tool source reads it.
    config: dict[str, Any] | None = None
    # Each stage's settings (source_settings.py), over the kind's defaults; validated as a whole.
    schedule: Json | None = None
    parsing: Json | None = None
    cleaning: Json | None = None
    ingest: Json | None = None
    rules: list[Json] | None = None
    metadata_mapping: list[Json] | None = None


class KbSourceLink(Out):
    source_id: str
    items_contributed: int
    rules: list[Json]


class KnowledgeBase(Out):
    id: str
    name: str
    slug: str
    # From the provisioning service: the template it was made from, and `system` or `managed`; null otherwise.
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
    # When an index last changed what the base holds.
    last_refreshed_at: str | None = None
    # When its sources were last read: the newest of their syncs.
    last_sync_at: str | None = None
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
    # file, web (a plugin source of one site's pages) or tool.
    kind: str
    name: str
    scope_summary: str
    config: Json
    parsing: Json
    cleaning: Json
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
    # On a settings save: the rebuild it started in the background, when items were built under other settings.
    rebuild: SyncRun | None = None
    # When the schedule next syncs it, and its health in one place (state, last good sync, days failing, tombstones).
    next_sync_at: str | None = None
    health: Json = Field(default_factory=dict[str, Any])


class NamedRef(Out):
    id: str
    name: str


class PluginSource(Out):
    # A source the team made from a plugin's knowledge source, for the app's resource list.
    id: str
    name: str
    source: str
    kb_ids: list[str]


class SourceRow(Source):
    used_by: list[NamedRef]
    running: bool


class KbSourceView(KbSourceLink):
    source: Source


class EmbeddingCoverage(Out):
    model: str
    width: int
    embedded: int
    units: int


class KnowledgeBaseDetail(KnowledgeBaseRow):
    attached: list[KbSourceView]
    # How many of the base's units have a vector of the environment's model; absent with no embedding model.
    embedding: EmbeddingCoverage | None = None
    metadata_keys: list[str]
    suggested_questions: list[str]
    held_count: int
    # What the caller may do with it, from the write routes' own check.
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
    # What the caller may do with it, from the write routes' own check.
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
    # A run in the background (a rebuild after a settings change): when it ended, and who asked it to stop.
    finished_at: str | None = None
    cancelled_by: str | None = None


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
    # The newer item with the same cleaned text, which search returns instead of this one.
    duplicate_of: str | None = None
    # Where a fetched item sits at its source: a library folder, a space's page tree.
    folder: str | None = None
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
    # How the file was read and what cleaning removed, page by page, from its stored reading.
    reading: Json | None = None
    # The splitting it was built under, and whether that is still the source's.
    settings_used: Json | None = None


class QueryIn(In):
    question: str


class PageIn(In):
    title: str = Field(max_length=200)
    text: str = Field(max_length=100_000)


class SearchIn(In):
    kb_ids: list[str]
    question: str
    # At most this many pieces; left out, the bases' own limit (their retrieval settings' chunkLimit) decides.
    limit: int | None = Field(default=None, ge=1, le=20)


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
    # The file the cited version was built from, which a citation opens; the item's address at its source.
    file_id: str | None = None
    url: str | None = None
    # What matched: the piece's own text, a smaller child, or a question written for it.
    matched: str = "self"
    # Each lane's own score: keyword, the share of the question's terms; meaning, cosine similarity.
    lanes: dict[str, float] = Field(default_factory=dict[str, float])
    verified: bool = False


class SkippedLane(Out):
    lane: str
    # no_embedding_model, no_vector_store, no_vectors, or embedding_unavailable with the model's code.
    reason: str


class Lanes(Out):
    asked: list[str]
    ran: list[str]
    skipped: list[SkippedLane]


class SearchCost(Out):
    embedding_tokens: int


class SearchOut(Out):
    passages: list[PassageOut]
    lanes: Lanes
    cost: SearchCost


class PlaygroundAnswer(Out):
    id: str
    question: str
    matchers: list[str]
    answer: str
    citations: list[Json]
    chunks: list[Json]
    no_answer: bool | None = None
    passages: list[PassageOut]
    lanes: Lanes
    cost: SearchCost
    retrieval_ms: int
    synthesis_ms: int
    shape: str


class FaqDraft(Out):
    question: str
    answer: str
    quote: str
    section_path: list[str]
    # Words the answer uses that its passage does not (beyond common words): an answer that may say more than its
    # source. Empty when every word is the passage's.
    adds_words: list[str] = Field(default_factory=list[str])


class DecideIn(In):
    ids: list[str] = Field(min_length=1, max_length=200)
    decision: Literal["approve", "reject"]


class DraftEdit(In):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=4000)


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
    # An FAQ draft's pair and the passage it quotes; absent for a sync's change.
    faq: FaqDraft | None = None


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


class SourceKind(Out):
    # `file` for the built-in kind; `tool` for an app's knowledge source, named by its plugin and source.
    type: str
    group: Literal["built_in", "apps"]
    title: str
    plugin: str | None = None
    source: str | None = None
    # Its items are one website's pages.
    site: bool = False
    # It needs the team's connection, and whether the team has one that works.
    needs_connection: bool = False
    connected: bool = False
    previews: bool = False
    pickers: bool = False
    # What a source of this kind is set up with (start addresses, sites, spaces).
    inputs: Json = Field(default_factory=dict[str, Any])
    # file, web or tool: the kind its defaults are chosen by.
    kind: str
    # The settings and schedule a new source of this kind starts with, as create applies them.
    defaults: Json


class AiApprovalIn(In):
    decision: Literal["approve", "revoke"]


class TokenRange(Out):
    low: int
    high: int


class AiEstimate(Out):
    steps: list[str]
    model: str
    sampled_items: int
    total_items: int
    calls: int
    input_tokens: int
    output_tokens: TokenRange
    # What the numbers rest on and what they leave out, in words.
    basis: str


class Tombstone(Out):
    id: str
    at: str | None = None
    reason: str | None = None


class TombstonesIn(In):
    ids: list[str] = Field(min_length=1, max_length=200)


class PreviewIn(In):
    # The plugin, its source and the source's own settings, as a create would send them.
    config: dict[str, Any]


class PreviewPage(Out):
    id: str
    # Will fetch, excluded by a rule, refused by robots.txt, needs JavaScript, ...
    outcome: str
    will_fetch: bool


class SourcePreview(Out):
    found: int
    will_fetch: int
    pages: list[PreviewPage]
    # The listing stopped at the source's page cap.
    capped: bool


class SourcePatch(In):
    name: str | None = None
    # A source read through an app: its own settings (a site's start, include and exclude, depth, pace), merged over
    # the saved ones and checked against what the plugin declares.
    values: Json | None = None
    collection: str | None = None
    owner: str | None = None
    sensitivity: str | None = None
    tags: list[str] | None = None
    # Each stage's settings; a part sent is merged into the saved one key by key and validated as a whole.
    schedule: Json | None = None
    parsing: Json | None = None
    cleaning: Json | None = None
    ingest: Json | None = None
    rules: list[Json] | None = None
    metadata_mapping: list[Json] | None = None


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
