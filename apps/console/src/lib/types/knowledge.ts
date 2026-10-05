/**
 * Data Hub knowledge: sources bring content in, knowledge bases index it for agents to search and cite.
 * Shapes follow the Docs AI model so the two products can share a backend.
 */

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

export type ChunkStrategy = 'structure' | 'topics' | 'faq' | 'headers' | 'summarise' | 'rows';

export interface ParsingSettings {
  ocr: boolean;
  tables: boolean;
  vision: boolean;
  removeHtml: boolean;
}

export interface ChunkingSettings {
  strategy: ChunkStrategy;
  size: number;
  overlap: number;
  language: string;
}

export interface Rule {
  id: string;
  kind: 'include' | 'exclude';
  field: 'path' | 'title' | 'mime' | 'modifiedAfter' | 'sizeUnder';
  value: string;
}

export interface MetadataMapping {
  key: string;
  /** `static:en` for a fixed value, `field:Dept` for a column at the source. */
  from: string;
}

export type Permissions = { mode: 'inherit' } | { mode: 'workspace' } | { mode: 'selected'; principals: string[] };

export interface Source {
  id: string;
  type: SourceType;
  name: string;
  connectionId?: string;
  connectionLabel?: string;
  scopeSummary: string;
  config: Record<string, unknown>;
  parsing: ParsingSettings;
  chunking: ChunkingSettings;
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
  reprocessPending?: boolean;
}

/** A source row as lists show it: knowledge base names and the running flag come joined from the API. */
export interface SourceRow extends Source {
  usedBy: { id: string; name: string }[];
  running: boolean;
}

export type ItemStatus = 'indexed' | 'pending' | 'processing' | 'failed' | 'partial' | 'excluded' | 'deleted';
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

export type SearchMode = 'semantic' | 'keyword' | 'hybrid';
export type CitationStyle = 'inline' | 'footnotes' | 'links' | 'none';

export interface MetadataFilter {
  key: string;
  op: 'equals' | 'in' | 'not';
  value: string;
}

export interface RetrievalSettings {
  searchMode: SearchMode;
  rerank: boolean;
  reranker: 'hosted' | 'cross-encoder';
  chunkLimit: number;
  threshold: number;
  queryRewrite: boolean;
  rewriteInstructions: string;
  /** Empty means every attached source. */
  scopeSourceIds: string[];
  synthesis: boolean;
  model: string;
  temperature: number;
  maxTokens: number;
  instructions: string;
  citationStyle: CitationStyle;
  includeChunks: boolean;
  noAnswerMessage: string;
  defaultFilters: MetadataFilter[];
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

export interface PrecedenceRule {
  id: string;
  label: string;
  winner: string;
  loser: string;
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
}

export type ConnectionStatus = 'connected' | 'needs_reauth' | 'disconnected';

/** A workspace-level connection to an app; every source of that type reuses it. */
export interface Connection {
  type: SourceType;
  name: string;
  status: ConnectionStatus;
  connectedAs?: string;
}

export interface SourcePreview {
  ok: boolean;
  message: string;
  rows: { title: string; path: string; size: number; modified: string }[];
}

/** A source read for its page: knowledge bases that read it, recent runs and error groups come joined. */
export interface SourceDetail extends Source {
  readers: Pick<KnowledgeBase, 'id' | 'name' | 'slug' | 'color' | 'health'>[];
  running?: SyncRun;
  recentRuns: SyncRun[];
  errorGroups: { message: string; count: number }[];
  itemCount: number;
}

export interface KnowledgeBaseInput {
  name: string;
  description: string;
  color: string;
  sourceIds: string[];
  preset: RetrievalPreset;
  collections: string[];
}

export type KnowledgeBasePatch = Partial<Pick<KnowledgeBase, 'name' | 'description' | 'color' | 'collections' | 'precedence'>> & {
  retrieval?: Partial<RetrievalSettings>;
};

export type SourceInput = Pick<
  Source,
  | 'type'
  | 'name'
  | 'scopeSummary'
  | 'config'
  | 'parsing'
  | 'chunking'
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
> & { status?: 'active' | 'draft'; itemsPending?: number };

export type SourcePatch = Partial<Omit<SourceInput, 'type'>> & { reprocessPending?: boolean };

export interface SyncOptions {
  full?: boolean;
  retry?: boolean;
}

export interface QueryInput {
  question: string;
  settings: RetrievalSettings;
  /** Answer as this staff member or role (see run-as.ts); omitted answers with the caller's own access. */
  runAsId?: string;
}

export type KbFilters = { health?: string[]; access?: string[] };
export type SourceFilters = { type?: string[]; status?: string[]; schedule?: string[]; usedBy?: string[] };
export type DocumentFilters = { sourceId?: string[]; status?: string[]; freshness?: string[]; sensitivity?: string[]; tags?: string[] };
export type ItemFilters = { status?: string[]; mime?: string[]; errorClass?: string[] };
export type RunFilters = { status?: string[]; trigger?: string[] };
