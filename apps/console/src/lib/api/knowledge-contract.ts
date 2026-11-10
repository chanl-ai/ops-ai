import type { BulkResult } from '@/lib/types/domain';
import type {
  AiEstimate,
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
  Rule,
  RunFilters,
  Source,
  SourceDetail,
  SourceFilters,
  SourceInput,
  SourceKindOption,
  SourceKindPreview,
  SourcePatch,
  SourceRow,
  SourceType,
  SyncOptions,
  SyncRun,
  Tombstone,
  WrittenItem,
  WrittenItemInput,
} from '@/lib/types/knowledge';
import type { SampleDocument, SplitPreview, SplitPreviewInput } from '@/lib/types/knowledge-ingest';
import type { ListParams, ListResult, OptionsPage, OptionsParams } from '@/lib/types/query';

/** Data Hub knowledge: knowledge bases, the sources that feed them, and the items sources produce. */
export interface KnowledgeApi {
  kbs: {
    list(params: ListParams<KbFilters>): Promise<ListResult<KnowledgeBaseRow>>;
    /** The knowledge picker: bases searched and paged on the server, storing their ids; `ids` labels stored ones. */
    options(p: OptionsParams): Promise<OptionsPage>;
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
    /** A titled text written in the console, indexed in the base's pages source; the same title saves its next version. */
    addPage(id: string, input: { title: string; text: string }): Promise<DocumentRow>;
    /** Files already in Files (each the team's and scanned clean), added to the base's documents source and synced. */
    addDocuments(id: string, fileIds: string[]): Promise<{ sourceId: string; files: { fileId: string; name: string }[]; run: SyncRun }>;
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
    /** Adds files already in Files (the team's, scanned clean) to a file source by id; the next sync indexes them. */
    addFiles(id: string, fileIds: string[]): Promise<{ fileId: string; name: string }[]>;
    /** Writes one item into a typed text or push source by its name, indexed at once; the same content is unchanged. */
    putItem(id: string, input: WrittenItemInput): Promise<WrittenItem>;
    /** Stops a running sync or rebuild between two items. */
    cancelRun(runId: string): Promise<SyncRun>;
    setPaused(id: string, paused: boolean): Promise<Source>;
    /** Addresses removed after answering gone twice, which syncs leave out until lifted. */
    tombstones(id: string): Promise<Tombstone[]>;
    liftTombstones(id: string, ids: string[]): Promise<Tombstone[]>;
    items(id: string, params: ListParams<ItemFilters>): Promise<ListResult<Item>>;
    runs(id: string, params: ListParams<RunFilters>): Promise<ListResult<SyncRun>>;
    run(runId: string): Promise<SyncRun>;
    /** What a website or app source with this `config` ({plugin, source, values}) would take in, without creating it. */
    preview(config: Record<string, unknown>): Promise<SourceKindPreview>;
    /** Required metadata of the chosen knowledge bases, and how many previewed items each would hold for it. */
    previewHeld(input: HeldPreviewInput): Promise<HeldPreview>;
    /** Seeded documents a split preview can run on; a source's own documents first when `sourceId` is given. */
    samples(sourceId?: string): Promise<SampleDocument[]>;
    /** Splits one sample document with the given settings, without saving anything. */
    previewSplit(input: SplitPreviewInput): Promise<SplitPreview>;
    /** What the source's AI steps would cost, from a split of up to 20 of its items with no model called. */
    aiEstimate(id: string): Promise<AiEstimate>;
    /** The knowledge owner approves the AI steps as now chosen, or takes the approval back. */
    decideAiSteps(id: string, decision: 'approve' | 'revoke'): Promise<Source>;
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
  /** Files, then each knowledge source of the team's apps that are on, with what a new one needs and starts with. */
  sourceKinds(): Promise<SourceKindOption[]>;
  /** Document owners, tags and source collections, for pickers. */
  lookups(): Promise<{ owners: string[]; tags: string[]; collections: string[] }>;
}
