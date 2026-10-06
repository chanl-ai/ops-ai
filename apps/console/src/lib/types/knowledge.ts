/**
 * Data Hub knowledge: sources bring content in, knowledge bases index it for agents to search and cite.
 * Shapes follow the Docs AI model so the two products can share a backend.
 */

import type { HeldReason, IngestSettings, ItemVersionRow, VersionStatus } from './knowledge-ingest';
import type { AnswerShape, FilterGroup, QueryMode, RetrievalTrace, RewriteMode, RuntimeValues, TableRowHit } from './knowledge-retrieval';

export type Sensitivity = 'internal' | 'confidential' | 'restricted';

export type SourceType = 'file' | 'url' | 'crawl' | 'text' | 'sharepoint' | 'confluence' | 'gdrive' | 'github' | 'notion' | 'zendesk' | 'salesforce';

export type SourceStatus = 'active' | 'paused' | 'draft' | 'revoked';
export type RunStatus = 'success' | 'partial' | 'failed' | 'running' | 'backing_off';
export type Schedule =
  | { kind: 'manual' }
  | { kind: 'daily'; time: string }
  | { kind: 'weekly'; day: string; time: string }
  | { kind: 'monthly'; day: number; time: string }
  | { kind: 'webhook'; safetyNetDaily: boolean };

/** Parsing before splitting. Stripping HTML is the `clean` ingestion strategy. */
export interface ParsingSettings {
  ocr: boolean;
  /** Keep tables as tables, so `table_rows` and structured values can read them. */
  tables: boolean;
  vision: boolean;
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

export interface Source {
  id: string;
  type: SourceType;
  name: string;
  /** The integration this source reads through; its status shows read-only on the source. */
  connectionId?: string;
  connectionLabel?: string;
  connection?: import('./integrations').ConnectionRef;
  scopeSummary: string;
  config: Record<string, unknown>;
  parsing: ParsingSettings;
  ingest: IngestSettings;
  /** Digest of the ingestion settings the current chunks were built with; differs from the settings when a re-index is needed. */
  indexedSettingsDigest?: string;
  rules: Rule[];
  metadataMapping: MetadataMapping[];
  tags: string[];
  titleFrom: 'source' | 'heading' | 'filename';
  permissions: Permissions;
  schedule: Schedule;
  deletedAtSource: 'remove' | 'keep_stale';
  staleAfterDays: number;
  notifyOnFailure: boolean;
  sensitivity: Sensitivity;
  /** Department boundary a knowledge base can be limited to. */
  collection: string;
  owner: string;
  status: SourceStatus;
  itemsIndexed: number;
  itemsFailed: number;
  itemsPending: number;
  lastSyncAt?: string;
  lastRunStatus?: RunStatus;
  lastRunDurationSec?: number;
  nextSyncAt?: string;
  cursor?: string;
  usedByKbIds: string[];
  createdAt: string;
}

/** A source row as lists show it: knowledge base names and the running flag come joined from the API. */
export interface SourceRow extends Source {
  usedBy: { id: string; name: string }[];
  running: boolean;
}

/** `held`: missing metadata a reading knowledge base requires, so it is stored but not searchable. */
export type ItemStatus = 'indexed' | 'pending' | 'processing' | 'failed' | 'partial' | 'excluded' | 'deleted' | 'held';
export type ErrorClass = 'parse' | 'fetch' | 'permission' | 'too_large' | 'rate_limited';

export interface Chunk {
  index: number;
  tokens: number;
  location: string;
  kind: 'content' | 'question' | 'answer' | 'summary' | 'row';
  text: string;
}

export interface Revision {
  n: number;
  author: string;
  date: string;
  sizeDelta: number;
  note?: string;
}

export interface Item {
  id: string;
  sourceId: string;
  externalId: string;
  title: string;
  mimeType: string;
  path: string;
  url?: string;
  modifiedAt: string;
  processedAt?: string;
  sizeBytes: number;
  status: ItemStatus;
  errorClass?: ErrorClass;
  error?: string;
  chunkCount: number;
  tags: string[];
  metadata: Record<string, string>;
  acl: string[];
  owner: string;
  version: string;
  effectiveDate: string;
  supersedes?: string;
  reviewBy: string;
  sensitivity: Sensitivity;
  collection: string;
  verified: boolean;
  queries30d: number;
  pageCount?: number;
  fileId?: string;
  /** Content digest; identical content across sources is indexed once. */
  digest: string;
  /** Items with the same family are versions of one document. */
  family: string;
  versionStatus: VersionStatus;
  supersededBy?: string;
  /** Set when this item's content is already indexed from another item; it adds no chunks. */
  duplicateOf?: { itemId: string; title: string; sourceName: string };
  /** Other sources holding the same content, on the item that is indexed. */
  alsoIn?: { itemId: string; title: string; sourceName: string }[];
  /** The source rule that excluded it, in words. */
  excludedBy?: string;
  held?: HeldReason;
}

/** A document as the knowledge base's Documents tab lists it. */
export interface DocumentRow extends Item {
  sourceName: string;
  freshness: 'fresh' | 'stale';
}

/** Heavy per-item content, fetched only when a document is opened. */
export interface ItemDetail {
  content: string;
  chunks: Chunk[];
  revisions: Revision[];
  /** Every version of this document, newest first. */
  versions: ItemVersionRow[];
}

export interface ItemWithDetail extends Item {
  sourceName: string;
  sourceType: SourceType;
  detail: ItemDetail;
}

export interface RunPhase {
  name: 'list' | 'fetch' | 'parse' | 'chunk' | 'embed' | 'upsert';
  durationMs: number;
  status: 'done' | 'running' | 'failed' | 'skipped';
}

export interface RunError {
  itemId: string;
  itemTitle: string;
  phase: RunPhase['name'];
  errorClass: ErrorClass;
  message: string;
}

export interface SyncRun {
  id: string;
  sourceId: string;
  trigger: 'manual' | 'schedule' | 'webhook' | 'full' | 'retry';
  startedAt: string;
  durationSec: number;
  status: RunStatus;
  cursorBefore?: string;
  cursorAfter?: string;
  cursorRejected?: boolean;
  counts: { listed: number; unchanged: number; upserted: number; deleted: number; failed: number; skipped: number };
  phases: RunPhase[];
  errors: RunError[];
  log: string[];
  progress?: { done: number; total: number; failed: number };
}

export type SearchMode = QueryMode;
export type CitationStyle = 'inline' | 'footnotes' | 'links' | 'none';

export interface RetrievalSettings {
  searchMode: QueryMode;
  /** Weight of the semantic score in hybrid mode, 0 to 1; the rest is keyword. */
  hybridWeight: number;
  rerank: boolean;
  reranker: 'hosted' | 'cross-encoder';
  chunkLimit: number;
  threshold: number;
  /** Date for `as_of`: only versions in force on it are searched. */
  asOf: string;
  rewrite: RewriteMode;
  /** Phrasings searched when `rewrite` is `expand`, including the original. */
  expandCount: number;
  rewriteInstructions: string;
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

export type KbHealth = 'healthy' | 'indexing' | 'degraded' | 'failed' | 'never';

export interface KbSourceLink {
  sourceId: string;
  itemsContributed: number;
  rules: Rule[];
}

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

export interface KnowledgeBase {
  id: string;
  name: string;
  slug: string;
  description: string;
  color: string;
  sources: KbSourceLink[];
  /** Department boundaries this knowledge base may read; empty means all. */
  collections: string[];
  precedence: PrecedenceRule[];
  metadataProfile: MetadataProfile;
  retrieval: RetrievalSettings;
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
  healthReasons: string[];
  lastRefreshedAt?: string;
  indexing?: { done: number; total: number; taskId: string };
  jobs: IndexJob[];
  createdAt: string;
}

/** A knowledge base row: source names and the agents that cite it come joined from the API. */
export interface KnowledgeBaseRow extends KnowledgeBase {
  sourceNames: string[];
  agentNames: string[];
}

/** One attached source as the knowledge base page shows it. */
export interface KbSourceView extends KbSourceLink {
  source: Source;
}

export interface KnowledgeBaseDetail extends KnowledgeBaseRow {
  attached: KbSourceView[];
  /** Metadata keys present on this knowledge base's documents, for filter editors. */
  metadataKeys: string[];
  suggestedQuestions: string[];
  /** Documents held for missing required metadata. */
  heldCount: number;
}

export interface Citation {
  n: number;
  documentId: string;
  title: string;
  section: string;
  page?: number;
  version: string;
  snippet: string;
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

export interface PlaygroundAnswer {
  id: string;
  question: string;
  /** Substrings of the question that select this canned answer in the mock. */
  matchers: string[];
  answer: string;
  citations: Citation[];
  chunks: ScoredChunk[];
  structured?: StructuredValue[];
  /** Which document precedence chose, said in the answer. */
  followed?: string;
  noAnswer?: boolean;
  retrievalMs: number;
  synthesisMs: number;
  /** Present when the question ran as someone else: what their permissions hid. */
  permissions?: import('./run-as').PermissionScope;
  shape?: AnswerShape;
  /** Rows matched by `table_lookup`. */
  rows?: TableRowHit[];
  trace?: RetrievalTrace;
}

export interface SourcePreview {
  ok: boolean;
  message: string;
  rows: { title: string; path: string; size: number; modified: string }[];
}

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
export interface SourceDetail extends Source {
  readers: Pick<KnowledgeBase, 'id' | 'name' | 'slug' | 'color' | 'health'>[];
  running?: SyncRun;
  recentRuns: SyncRun[];
  errorGroups: { message: string; count: number }[];
  itemCount: number;
  /** The ingestion settings changed since the chunks were built. */
  reindexNeeded: boolean;
  /** Metadata keys the knowledge bases reading this source require. */
  requiredMetadata: string[];
  /** Items excluded by a rule, held for metadata, or indexed once elsewhere. */
  governance: { excluded: number; held: number; duplicates: number; superseded: number };
  /** AI ingest steps still waiting for approval; syncs and re-indexes run without them. */
  aiStepsWaiting: string[];
  /** Whether the current user may approve the waiting steps, and what approving starts. */
  approval?: { canApprove: boolean; blockedReason?: string; modelCalls: number; estimatedCost: string; items: number };
}

export interface KnowledgeBaseInput {
  name: string;
  description: string;
  color: string;
  sourceIds: string[];
  preset: RetrievalPreset;
  collections: string[];
}

export type KnowledgeBasePatch = Partial<Pick<KnowledgeBase, 'name' | 'description' | 'color' | 'collections' | 'precedence' | 'metadataProfile'>> & {
  retrieval?: Partial<RetrievalSettings>;
};

export type SourceInput = Pick<
  Source,
  | 'type'
  | 'name'
  | 'scopeSummary'
  | 'config'
  | 'parsing'
  | 'ingest'
  | 'rules'
  | 'metadataMapping'
  | 'tags'
  | 'titleFrom'
  | 'permissions'
  | 'schedule'
  | 'deletedAtSource'
  | 'staleAfterDays'
  | 'notifyOnFailure'
  | 'sensitivity'
  | 'collection'
  | 'connectionId'
> & {
  status?: 'active' | 'draft';
  itemsPending?: number;
  /** File sources: ids from the Files API. The source never receives bytes; it reads each file from storage. */
  fileIds?: string[];
};

export type SourcePatch = Partial<Omit<SourceInput, 'type'>>;

export interface SyncOptions {
  full?: boolean;
  retry?: boolean;
}

export interface QueryInput {
  question: string;
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
export type SourceFilters = { type?: string[]; status?: string[]; schedule?: string[]; usedBy?: string[] };
export type DocumentFilters = { sourceId?: string[]; status?: string[]; freshness?: string[]; sensitivity?: string[]; tags?: string[] };
export type ItemFilters = { status?: string[]; mime?: string[]; errorClass?: string[] };

export type { HeldReason, IngestSettings, ItemVersionRow, VersionStatus } from './knowledge-ingest';
export type RunFilters = { status?: string[]; trigger?: string[] };
