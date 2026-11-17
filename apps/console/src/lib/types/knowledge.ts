/**
 * Data Hub knowledge: sources bring content in, knowledge bases index it for agents to search and cite.
 * Shapes follow the Docs AI model so the two products can share a backend.
 */

import type { OpsAI } from '@chanl-ai/ops-ai';

import type { HeldReason, IngestSettings, ItemVersionRow, VersionStatus } from './knowledge-ingest';
import type { AnswerShape, FilterGroup, QueryMode, RetrievalTrace, RewriteMode, RuntimeValues, TableRowHit } from './knowledge-retrieval';

import type { Narrow } from './served';

// Entity types come from the generated SDK (kb-service's OpenAPI document), so a field renamed there fails the console's typecheck.
type Kb = OpsAI['raw']['kb'];
type Reply<K extends keyof Kb> = Awaited<ReturnType<Kb[K]>>;
type Body<K extends keyof Kb> = NonNullable<NonNullable<Parameters<Kb[K]>[0]>['body']>;

export type Sensitivity = 'internal' | 'confidential' | 'restricted';

export type SourceType = 'file' | 'url' | 'crawl' | 'text' | 'push' | 'sharepoint' | 'confluence' | 'gdrive' | 'github' | 'notion' | 'zendesk' | 'salesforce' | 'tool';

export type SourceStatus = 'active' | 'paused' | 'draft' | 'revoked';
export type RunStatus = 'running' | 'success' | 'partial' | 'failed' | 'cancelled' | 'skipped';
/** What started a run: a person (manual, full, retry), the schedule, or a settings save that rebuilds items. */
export type RunTrigger = 'manual' | 'schedule' | 'full' | 'retry' | 'settings';
export type Weekday = 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun';
/** When a source syncs on its own; `tz` is an IANA time zone. */
export type Schedule =
  | { kind: 'manual' }
  | { kind: 'hourly'; every: 1 | 2 | 4 | 6 | 12 }
  | { kind: 'daily'; time: string; tz: string }
  | { kind: 'weekly'; day: Weekday; time: string; tz: string };

export type OcrMode = 'off' | 'auto' | 'always';

/** How documents-service reads the source's files. */
export interface ParsingSettings {
  /** `auto` reads scanned pages and the picture parts of mixed pages. */
  ocr: OcrMode;
  tables: boolean;
  vision: boolean;
}

/** What is removed between reading and splitting. */
export interface CleaningSettings {
  /** Drops menus, footers, banners and other blocks the reading marked as page furniture. */
  furniture: boolean;
  /** Keeps a page's main article when it has one. */
  mainContent: boolean;
  /** Drops a line found on more than half of a website source's pages. */
  siteRepeats: boolean;
  /** An item with the same cleaned text as another in a base it feeds: flag both and search the newer, or skip it. */
  duplicates: 'flag' | 'skip';
}

/** What a source is: uploaded files, one website's pages, or another app's knowledge source. */
export type SourceKind = 'file' | 'text' | 'push' | 'web' | 'tool';

/** A source's sync health, kept by kb-service as each run settles. */
export interface SourceHealth {
  state: 'never' | 'healthy' | 'failing' | 'needs_reconnect';
  lastGoodSyncAt?: string;
  failingSince?: string;
  daysFailing: number;
  /** Failed runs in a row. */
  failedRuns: number;
  /** Addresses removed for answering gone twice. */
  tombstoned: number;
}

export interface Rule {
  id: string;
  kind: 'include' | 'exclude';
  field: 'path' | 'title' | 'mime' | 'modifiedAfter' | 'sizeUnder';
  value: string;
}

export interface MetadataMapping {
  key: string;
  /** `static:en` for a fixed value, `field:Dept` for a column at the source, `ai:product` to extract it with a model at ingest. */
  from: string;
}

export type Permissions = { mode: 'inherit' } | { mode: 'workspace' } | { mode: 'selected'; principals: string[] };

/** What the generator types loosely on a source, as the console reads it. */
type SourceNarrow = {
  type: SourceType;
  kind: SourceKind;
  parsing: ParsingSettings;
  cleaning: CleaningSettings;
  ingest: IngestSettings;
  /** Hosts of the source's own site an admin has yet to approve, with the Security task each waits on; nothing is fetched until then. */
  waitingHosts: { host: string; runKey?: string | null }[];
  rules: Rule[];
  metadataMapping: MetadataMapping[];
  titleFrom: 'source' | 'heading' | 'filename';
  permissions: Permissions;
  schedule: Schedule;
  deletedAtSource: 'remove' | 'keep_stale';
  sensitivity: Sensitivity;
  status: SourceStatus;
  lastRunStatus?: RunStatus | null;
  health?: SourceHealth;
  /** The settings rebuild running in the background, when a save started one. */
  rebuild?: SyncRun | null;
};

/** Fields the console shows that kb-service does not return on a source yet. */
type SourceViewOnly = {
  /** The integration this source reads through; its status shows read-only on the source. */
  connectionId?: string;
  connectionLabel?: string;
  connection?: import('./integrations').ConnectionRef;
  /** Digest of the ingestion settings the current chunks were built with; differs from the settings when a re-index is needed. */
  indexedSettingsDigest?: string;
  lastRunDurationSec?: number | null;
  cursor?: string;
};

export type Source = Narrow<Reply<'sources_create_source'>, SourceNarrow> & SourceViewOnly;

/** A source row as lists show it: knowledge base names and the running flag come joined from the API. */
export type SourceRow = Narrow<Reply<'sources_list_sources'>['data'][number], SourceNarrow> & SourceViewOnly;

/** `held`: missing metadata a reading knowledge base requires, so it is stored but not searchable. */
export type ItemStatus = 'indexed' | 'pending' | 'processing' | 'failed' | 'partial' | 'excluded' | 'deleted' | 'held';
export type ErrorClass = 'parse' | 'fetch' | 'permission' | 'too_large' | 'rate_limited';

export interface Chunk {
  index: number;
  tokens: number;
  location: string;
  /** The PDF page the passage is on, when the document has pages. */
  page?: number;
  kind: 'content' | 'question' | 'answer' | 'summary' | 'row';
  text: string;
  /** What search matches for this piece: its own text, its children, its questions and approved FAQ pairs. */
  units?: { kind: string; text: string }[];
  /** Fields kept on the piece for filters. */
  metadata?: Record<string, string>;
}

/** How an item's file was read, page by page, and what cleaning removed; null with no file or no finished reading. */
export interface ItemReading {
  readerVersion?: string | null;
  ocr: string;
  pages: { number: number; readBy?: string | null; blocks: Record<string, number>; removedChars: number; ocrConfidence?: number }[];
}

/** The settings the item was split under, and whether they are still the source's (false: it waits for a rebuild). */
export interface ItemSettingsUsed {
  preset: string;
  strategies: string[];
  indexedWith?: string | null;
  current: boolean;
}

export interface Revision {
  n: number;
  author: string;
  date: string;
  sizeDelta: number;
  note?: string;
}

type ItemNarrow = {
  status: ItemStatus;
  errorClass?: ErrorClass | null;
  freshness: 'fresh' | 'stale' | 'no_schedule';
  sensitivity: Sensitivity;
  versionStatus: VersionStatus;
};

/** Fields the console shows that kb-service does not return on an item yet. */
type ItemViewOnly = {
  supersedes?: string;
  supersededBy?: string;
  /** Other sources holding the same content, on the item that is indexed. */
  alsoIn?: { itemId: string; title: string; sourceName: string }[];
  /** The source rule that excluded it, in words. */
  excludedBy?: string;
  held?: HeldReason;
};

/** kb-service answers `duplicateOf` as the id of the item whose content this one repeats. */
export type Item = Narrow<Reply<'sources_put_item'>['item'], ItemNarrow> & ItemViewOnly;

/** A document as the knowledge base's Documents tab lists it. */
/** What a document is, as kb-service names it for the Documents table's Type column and filter. */
export type DocType = 'pdf' | 'word' | 'spreadsheet' | 'slides' | 'web' | 'text' | 'typed' | 'app' | 'other';

export type DocumentRow = Narrow<Reply<'knowledge_bases_list_documents'>['data'][number], ItemNarrow> & ItemViewOnly;

/** Heavy per-item content, fetched only when a document is opened. */
export interface ItemDetail {
  content: string;
  chunks: Chunk[];
  revisions: Revision[];
  /** Every version of this document, newest first. */
  versions: ItemVersionRow[];
}

export type ItemWithDetail = Narrow<Reply<'items_get_item'>, ItemNarrow & { sourceType: SourceType; detail: ItemDetail; reading?: ItemReading | null; settingsUsed?: ItemSettingsUsed | null }> & ItemViewOnly;

/** One item or listing a run could not take in, with the step it failed at and why. */
export interface RunError {
  itemId?: string;
  itemTitle?: string;
  /** The step: list, get, store or parse. */
  phase: string;
  errorClass: string;
  message: string;
}

/**
 * A run's counts. A sync counts what it listed, left unchanged, took in, removed, failed, skipped or excluded; a
 * settings rebuild counts its total, checked, rebuilt and failed items. Model use is present when an AI step ran.
 */
export interface RunCounts {
  listed?: number;
  unchanged?: number;
  upserted?: number;
  deleted?: number;
  failed?: number;
  skipped?: number;
  excluded?: number;
  reading?: number;
  total?: number;
  checked?: number;
  rebuilt?: number;
  modelCalls?: number;
  inputTokens?: number;
  outputTokens?: number;
}

export type SyncRun = Narrow<Reply<'sources_get_run'>, { trigger: RunTrigger; status: RunStatus; counts: RunCounts; errors: RunError[] }>;

/** An address removed after answering gone twice; a sync leaves it out until it is lifted. */
export type Tombstone = Reply<'sources_list_tombstones'>[number];

export type SearchMode = QueryMode;
export type CitationStyle = 'inline' | 'footnotes' | 'links' | 'none';

export interface RetrievalSettings {
  searchMode: QueryMode;
  /** Weight of the semantic score in hybrid mode, 0 to 1; the rest is keyword. */
  hybridWeight: number;
  rerank: boolean;
  reranker: 'hosted' | 'cross-encoder';
  chunkLimit: number;
  /** Keyword floor: the share of the question's words a piece must hold. */
  threshold: number;
  /** Meaning floor: how close in meaning a piece must be. */
  meaningThreshold?: number;
  /** Collections this base searches; empty means every collection. */
  scopeCollections?: string[];
  /** Date for `as_of`: only versions in force on it are searched. */
  asOf: string;
  rewrite: RewriteMode;
  /** Phrasings searched when `rewrite` is `expand`, including the original. */
  expandCount: number;
  rewriteInstructions: string;
  /** The models-service chat alias rerank and rewrite call; empty uses the installation's default. */
  queryModel?: string;
  /** Empty means every attached source. */
  scopeSourceIds: string[];
  answerShape: AnswerShape;
  model: string;
  temperature: number;
  maxTokens: number;
  instructions: string;
  citationStyle: CitationStyle;
  includeChunks: boolean;
  noAnswerMessage: string;
  filters: FilterGroup;
  tagsInclude: string[];
  tagsExclude: string[];
  includeUntagged: boolean;
  structuredTables: boolean;
}

export type RetrievalPreset = 'balanced' | 'precise' | 'raw';

/** What a search of the base gives back to an agent's turn; the agents kernel applies it (kb-service `answer`). */
export interface AnswerSettings {
  shape: 'answer_with_citations' | 'chunks';
  /** An answer citing none of the base's pieces is replaced by `noAnswerMessage`. */
  withholdUncited: boolean;
  noAnswerMessage: string;
}

/** How syncs of the base's sources treat what they find (kb-service `sync`). */
export interface SyncSettings {
  changes: 'apply' | 'review';
  removedAtSource: 'remove' | 'keep';
  staleAfterDays: number;
  notifyOnFailure: boolean;
}

/** How a new source of the base splits; each source keeps its own copy (kb-service `sourceDefaults`). */
export interface BaseSourceDefaults {
  strategies: ('structure' | 'fixed' | 'context_headers' | 'parent_child' | 'table_rows' | 'clean')[];
  size: number;
  overlap: number;
  childSize: number;
}

export type KbHealth = 'healthy' | 'indexing' | 'degraded' | 'failed' | 'never';

export type KbSourceLink = Narrow<NonNullable<Reply<'knowledge_bases_create_knowledge_base'>['sources']>[number], { rules: Rule[] }>;

/**
 * When two returned chunks cover the same topic, the first matching rule decides which one is used. `class`
 * compares the documents' `doc_class` metadata (`winner` beats `loser`); `newer` keeps the later effective date.
 */
export interface PrecedenceRule {
  id: string;
  label: string;
  kind: 'class' | 'newer';
  winner: string;
  loser: string;
}

/** Metadata every document must carry before this knowledge base searches it; items without it are held. */
export interface MetadataProfile {
  required: string[];
}

export interface KbAccess {
  members: { mode: 'all' | 'selected'; principals: string[] };
  anyApiKey: boolean;
  mcp: { enabled: boolean; toolName: string };
  publicLink: { enabled: boolean; slug: string; answerStyle: 'chat' | 'single'; password?: string; rateLimit: 60 | 300 | 1000; showSourceLinks: boolean };
  documentPermissions: 'respect' | 'workspace';
}

export interface IndexJob {
  id: string;
  startedAt: string;
  durationSec: number;
  processed: number;
  failed: number;
  status: RunStatus;
  trigger: string;
}

type KbNarrow = {
  sources: KbSourceLink[];
  precedence: PrecedenceRule[];
  metadataProfile: MetadataProfile;
  retrieval: RetrievalSettings;
  answer: AnswerSettings;
  sync: SyncSettings;
  sourceDefaults: BaseSourceDefaults;
  access: KbAccess;
  automation: 'act' | 'suggest';
  stats: {
    documents: number;
    chunks: number;
    failures: number;
    stale: number;
    queries7d: number;
    queriesChange7d: number;
    noAnswerRate: number;
    medianLatencyMs: number;
  };
  health: KbHealth;
  indexing?: { done: number; total: number; taskId: string } | null;
  jobs: IndexJob[];
};

export type KnowledgeBase = Narrow<Reply<'knowledge_bases_create_knowledge_base'>, KbNarrow>;

/** A knowledge base row: source names and the agents that cite it come joined from the API. */
export type KnowledgeBaseRow = Narrow<Reply<'knowledge_bases_list_knowledge_bases'>['data'][number], KbNarrow>;

/** One attached source as the knowledge base page shows it; a sync or rebuild holds `running`, and the base's detail polls while any does. */
export type KbSourceView = Narrow<NonNullable<Reply<'knowledge_bases_get_knowledge_base'>['attached']>[number], { rules: Rule[]; source: Source }>;

/** How many of a base's search units have a vector in the base's embedding model; null with no embedding model. */
export type EmbeddingCoverage = NonNullable<Reply<'knowledge_bases_get_knowledge_base'>['embedding']>;

export type KnowledgeBaseDetail = Narrow<Reply<'knowledge_bases_get_knowledge_base'>, KbNarrow & { attached: KbSourceView[] }>;

export interface Citation {
  n: number;
  documentId: string;
  title: string;
  section: string;
  page?: number;
  version: string;
  snippet: string;
  /** Set when the passage is from a file attached in the conversation: the citation opens it in Files. */
  fileId?: string;
  url?: string;
  precedenceNote?: string;
  /** Past its review-by date; still served, flagged wherever the citation shows. */
  stale?: boolean;
  /** The source's connection was revoked, so this passage no longer updates from the source. */
  connectionRevoked?: boolean;
  /** As-of answers: the date the cited version was in force, and whether a later version has replaced it since. */
  inForceOn?: string;
  supersededToday?: boolean;
}

export interface ScoredChunk {
  chunkId: string;
  documentId: string;
  documentTitle: string;
  sourceName: string;
  score: number;
  location: string;
  text: string;
  rejected: boolean;
  version: string;
}

export interface StructuredValue {
  label: string;
  value: string;
  unit?: string;
  from: string;
}

/** What a search of a base answers, as `POST /v1/knowledge-bases/{id}/query` returns it, plus what only the mock fills in. */
export type PlaygroundAnswer = Narrow<Reply<'knowledge_bases_query_knowledge_base'>, { shape: AnswerShape; citations: Citation[]; chunks: ScoredChunk[] }> & {
  structured?: StructuredValue[];
  /** Which document precedence chose, said in the answer. */
  followed?: string;
  /** Present when the question ran as someone else: what their permissions hid. */
  permissions?: import('./run-as').PermissionScope;
  /** Rows matched by `table_lookup`. */
  rows?: TableRowHit[];
  trace?: RetrievalTrace;
};

export type SearchPassage = NonNullable<Reply<'knowledge_bases_query_knowledge_base'>['passages']>[number];

/** What a new source's previewed items would look like to the knowledge bases chosen for attachment (spec 5.15.10). */
export interface HeldPreviewInput extends Pick<SourceInput, 'type' | 'config' | 'metadataMapping'> {
  kbIds: string[];
}

export interface HeldPreview {
  /** Previewed items the counts cover. */
  items: number;
  byKb: { kbId: string; kbName: string; required: string[]; held: number; missing: string[] }[];
}

/** A source read for its page: knowledge bases that read it, recent runs and error groups come joined. */
export type SourceDetail = Narrow<
  Reply<'sources_get_source'>,
  SourceNarrow & {
    readers: Pick<KnowledgeBase, 'id' | 'name' | 'slug' | 'color' | 'health'>[];
    running?: SyncRun | null;
    recentRuns: SyncRun[];
    errorGroups: { message: string; count: number }[];
    /** Items excluded by a rule, held for metadata, or indexed once elsewhere. */
    governance: { excluded: number; held: number; duplicates: number; superseded: number };
  }
> &
  SourceViewOnly & {
    /** Whether the current user may approve the waiting steps, and what approving starts; kb-service does not return it yet. */
    approval?: { canApprove: boolean; blockedReason?: string; modelCalls: number; estimatedCost: string; items: number };
  };

export interface KnowledgeBaseInput {
  name: string;
  /** The person who answers for what it serves, by email; they or a team admin may change it. */
  owner: string;
  description: string;
  color: string;
  sourceIds: string[];
  preset: RetrievalPreset;
  collections: string[];
}

export type KnowledgeBasePatch = Partial<Pick<KnowledgeBase, 'name' | 'description' | 'color' | 'collections' | 'precedence' | 'metadataProfile' | 'owner'>> & {
  /** Each section merges over what is stored: the keys sent change, the rest stay. */
  retrieval?: Partial<RetrievalSettings>;
  answer?: Partial<AnswerSettings>;
  sync?: Partial<SyncSettings>;
  sourceDefaults?: Partial<BaseSourceDefaults>;
  /** Who may search a base is its whole team; only the MCP tool is set here. */
  access?: { mcp: Partial<KbAccess['mcp']> };
};

/** A new source, as `POST /v1/sources` takes it; settings left out start from its kind's defaults. */
export type SourceInput = Pick<Source, 'type' | 'name'> &
  Partial<Pick<Source, 'config' | 'parsing' | 'cleaning' | 'rules' | 'metadataMapping' | 'schedule' | 'sensitivity' | 'collection' | 'tags' | 'owner'>> & {
    status?: 'active' | 'draft';
    /** Merged over the kind's defaults, so Add source sends only the steps it switches. */
    ingest?: Partial<IngestSettings>;
    /** File sources: ids from the Files API. The source never receives bytes; it reads each file from storage. */
    fileIds?: string[];
  };

/** What a save may change. `values` are a website or app source's own settings, checked against what its plugin declares. */
export type SourcePatch = Partial<Pick<Source, 'name' | 'collection' | 'owner' | 'sensitivity' | 'tags' | 'parsing' | 'cleaning' | 'ingest' | 'rules' | 'metadataMapping' | 'schedule'>> & {
  values?: Record<string, unknown>;
};

/** One setting an app's knowledge source is set up with, as its plugin declares it. */
export interface SourceInputField {
  type?: 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array';
  description?: string;
  required?: boolean;
  default?: unknown;
  enum?: (string | number | boolean)[];
  items?: SourceInputField;
  /** The kind of scope (site, library, space) this input's values are picked from through the source's scopes tool. */
  picker?: string;
}

/** One thing a plugin source can be pointed at, as its scopes tool answers: a site, a library, a space. */
export interface ScopeOption {
  id: string;
  title: string;
  kind: string;
  parent?: string;
  detail?: string;
}

export interface ScopesInput {
  plugin: string;
  source: string;
  query?: string;
  /** What one picked scope holds (a site's libraries). */
  parent?: string;
  cursor?: string;
}

/** What a new source's settings start as for its kind; Add source's Review shows them. */
export interface SourceDefaults {
  parsing: ParsingSettings;
  cleaning: CleaningSettings;
  ingest: IngestSettings;
  rules: Rule[];
  metadataMapping: MetadataMapping[];
  schedule: Schedule;
}

/** A kind of source the team may add: Files, or a knowledge source of one of its apps. */
export type SourceKindOption = Narrow<
  Reply<'sources_source_kinds'>[number],
  {
    type: 'file' | 'text' | 'push' | 'tool';
    kind: SourceKind;
    cannotCreateCode?: 'connection_missing' | 'sign_in_not_team' | null;
    inputs?: Record<string, SourceInputField>;
    defaults: SourceDefaults;
  }
>;

/** What a website or app source with these settings would take in, before anything is stored. */
export type SourceKindPreview = Reply<'sources_preview_source'>;

/** What the AI steps of a source would cost, from a split of up to 20 of its items with no model called. */
export type AiEstimate = Reply<'sources_estimate_ai_steps'>;

export interface SyncOptions {
  full?: boolean;
  retry?: boolean;
}

export interface QueryInput {
  question: string;
  /** Only pieces of this collection (the Test sheet's filter). */
  collection?: string;
  /** Full settings for this call; omitted uses each knowledge base's saved settings. */
  settings?: RetrievalSettings;
  /** Fields that override the saved settings for this call only (workflow steps, chat). */
  overrides?: Partial<RetrievalSettings>;
  /** Values for runtime variables in filters. */
  runtime?: RuntimeValues;
  /** Answer as this staff member or role (see run-as.ts); omitted answers with the caller's own access. */
  runAsId?: string;
  /** Further knowledge bases to search with this one; their precedence rules apply after this one's. */
  alsoKbIds?: string[];
}

/** A question over one or more knowledge bases. */
export interface RetrieveInput extends Omit<QueryInput, 'alsoKbIds'> {
  kbIds: string[];
}

export type KbFilters = { health?: string[]; access?: string[] };
export type SourceFilters = { type?: string[]; status?: string[]; schedule?: string[]; usedBy?: string[]; connectionId?: string[] };
export type DocumentFilters = { sourceId?: string[]; status?: string[]; collection?: string[]; docType?: string[]; freshness?: string[]; sensitivity?: string[]; tags?: string[] };
export type ItemFilters = { status?: string[]; mime?: string[]; errorClass?: string[] };

export type { HeldReason, IngestSettings, ItemVersionRow, VersionStatus } from './knowledge-ingest';
export type RunFilters = { status?: string[]; trigger?: string[] };

/** One item written into a typed text or push source, by name: the same name and content again changes nothing. */
export interface WrittenItemInput {
  name: string;
  title?: string;
  /** Markdown unless `mime` names another text type. */
  text?: string;
  /** A file's bytes in base64, with its `mime`. */
  content?: string;
  mime?: string;
}

export type WrittenItem = Narrow<Reply<'sources_put_item'>, { item: Item }>;
