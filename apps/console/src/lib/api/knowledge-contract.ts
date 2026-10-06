import type { BulkResult } from '@/lib/types/domain';
import type {
  HeldPreview,
  HeldPreviewInput,
  DocumentFilters,
  DocumentRow,
  Item,
  ItemFilters,
  ItemWithDetail,
  KbFilters,
  KnowledgeBase,
  KnowledgeBaseDetail,
  KnowledgeBaseInput,
  KnowledgeBasePatch,
  KnowledgeBaseRow,
  PlaygroundAnswer,
  QueryInput,
  RetrieveInput,
  Rule,
  RunFilters,
  Source,
  SourceDetail,
  SourceFilters,
  SourceInput,
  SourcePatch,
  SourcePreview,
  SourceRow,
  SourceType,
  SyncOptions,
  SyncRun,
} from '@/lib/types/knowledge';
import type { SampleDocument, SplitPreview, SplitPreviewInput } from '@/lib/types/knowledge-ingest';
import type { ListParams, ListResult } from '@/lib/types/query';

/** Data Hub knowledge: knowledge bases, the sources that feed them, and the items sources produce. */
export interface KnowledgeApi {
  kbs: {
    list(params: ListParams<KbFilters>): Promise<ListResult<KnowledgeBaseRow>>;
    get(id: string): Promise<KnowledgeBaseDetail>;
    create(input: KnowledgeBaseInput): Promise<KnowledgeBase>;
    update(id: string, patch: KnowledgeBasePatch): Promise<KnowledgeBase>;
    remove(id: string): Promise<void>;
    /** Copies settings and source links; the copy starts unindexed. */
    duplicate(id: string): Promise<KnowledgeBase>;
    refresh(id: string): Promise<KnowledgeBase>;
    cancelJob(id: string): Promise<KnowledgeBase>;
    retryFailed(id: string): Promise<KnowledgeBase>;
    attachSources(id: string, sourceIds: string[]): Promise<KnowledgeBase>;
    detachSource(id: string, sourceId: string): Promise<KnowledgeBase>;
    setSourceRules(id: string, sourceId: string, rules: Rule[]): Promise<KnowledgeBase>;
    documents(id: string, params: ListParams<DocumentFilters>): Promise<ListResult<DocumentRow>>;
    /** Searches this knowledge base (and `alsoKbIds`) and returns the answer with its retrieval trace. */
    query(id: string, input: QueryInput): Promise<PlaygroundAnswer>;
    bulkRefresh(ids: string[]): Promise<BulkResult>;
    bulkRemove(ids: string[]): Promise<BulkResult>;
  };
  sources: {
    list(params: ListParams<SourceFilters>): Promise<ListResult<SourceRow>>;
    get(id: string): Promise<SourceDetail>;
    /** `sync` starts the first run straight away; `kbIds` attaches the new source to those knowledge bases. */
    create(input: SourceInput, opts?: { sync?: boolean; kbIds?: string[] }): Promise<Source>;
    update(id: string, patch: SourcePatch): Promise<Source>;
    remove(id: string): Promise<void>;
    sync(id: string, opts?: SyncOptions): Promise<SyncRun>;
    cancelRun(id: string): Promise<void>;
    setPaused(id: string, paused: boolean): Promise<Source>;
    /** Rebuilds every item with the current parsing and chunking settings. */
    reprocess(id: string): Promise<SyncRun>;
    items(id: string, params: ListParams<ItemFilters>): Promise<ListResult<Item>>;
    runs(id: string, params: ListParams<RunFilters>): Promise<ListResult<SyncRun>>;
    run(runId: string): Promise<SyncRun>;
    /** Lists what a source would fetch, without creating it. */
    preview(input: Pick<SourceInput, 'type' | 'config'>): Promise<SourcePreview>;
    /** Required metadata of the chosen knowledge bases, and how many previewed items each would hold for it. */
    previewHeld(input: HeldPreviewInput): Promise<HeldPreview>;
    /** Seeded documents a split preview can run on; a source's own documents first when `sourceId` is given. */
    samples(sourceId?: string): Promise<SampleDocument[]>;
    /** Splits one sample document with the given settings, without saving anything. */
    previewSplit(input: SplitPreviewInput): Promise<SplitPreview>;
    /** The knowledge owner approves the source's AI ingestion steps. */
    approveIngest(id: string): Promise<Source>;
    bulkSync(ids: string[]): Promise<BulkResult>;
    bulkSetPaused(ids: string[], paused: boolean): Promise<BulkResult>;
    bulkRemove(ids: string[]): Promise<BulkResult>;
  };
  items: {
    get(id: string): Promise<ItemWithDetail>;
    reprocess(ids: string[]): Promise<BulkResult>;
    /** Adds an exclude rule for each item's path on its source. */
    exclude(ids: string[]): Promise<BulkResult>;
    verify(id: string, verified: boolean): Promise<Item>;
    setTags(id: string, tags: string[]): Promise<Item>;
    setOwner(id: string, owner: string): Promise<Item>;
    addTag(ids: string[], tag: string): Promise<BulkResult>;
    /** Supplies metadata a held item is missing; it becomes searchable when nothing required is left. */
    setMetadata(id: string, values: Record<string, string>): Promise<Item>;
  };
  /** Searches several knowledge bases with each one's saved settings unless `settings` or `overrides` say otherwise. Used by chat and workflow knowledge steps. */
  retrieve(input: RetrieveInput): Promise<PlaygroundAnswer>;
  /** Document owners, tags and source collections, for pickers. */
  lookups(): Promise<{ owners: string[]; tags: string[]; collections: string[] }>;
}
