'use client';

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type {
  DocumentFilters,
  ItemFilters,
  KbFilters,
  KnowledgeBaseInput,
  KnowledgeBasePatch,
  QueryInput,
  RetrieveInput,
  Rule,
  RunFilters,
  SourceFilters,
  HeldPreviewInput,
  SourceInput,
  SourcePatch,
  SyncOptions,
} from '@/lib/types/knowledge';
import type { SplitPreviewInput } from '@/lib/types/knowledge-ingest';
import type { ListParams } from '@/lib/types/query';

/** Every knowledge key starts with 'knowledge', so one invalidation refreshes lists, records and counts. */
export const kk = {
  kbs: (p: unknown) => ['knowledge', 'kbs', p] as const,
  kb: (id: string) => ['knowledge', 'kb', id] as const,
  documents: (id: string, p: unknown) => ['knowledge', 'kb', id, 'documents', p] as const,
  sources: (p: unknown) => ['knowledge', 'sources', p] as const,
  source: (id: string) => ['knowledge', 'source', id] as const,
  items: (id: string, p: unknown) => ['knowledge', 'source', id, 'items', p] as const,
  runs: (id: string, p: unknown) => ['knowledge', 'source', id, 'runs', p] as const,
  run: (id: string) => ['knowledge', 'run', id] as const,
  item: (id: string) => ['knowledge', 'item', id] as const,
  lookups: ['knowledge', 'lookups'] as const,
  samples: (sourceId?: string) => ['knowledge', 'samples', sourceId ?? 'all'] as const,
};

const paged = { placeholderData: keepPreviousData };
/** While an index refresh or sync runs, poll so progress moves without a reload. */
const POLL_MS = 1500;
const pollWhile = (running: boolean) => (running ? POLL_MS : false);

export const useKnowledgeBases = (p: ListParams<KbFilters>) =>
  useQuery({ queryKey: kk.kbs(p), queryFn: () => api.knowledge.kbs.list(p), ...paged, refetchInterval: (q) => pollWhile(!!q.state.data?.data.some((k) => k.indexing)) });
export const useKnowledgeBase = (id: string) =>
  useQuery({ queryKey: kk.kb(id), queryFn: () => api.knowledge.kbs.get(id), refetchInterval: (q) => pollWhile(!!q.state.data?.indexing) });
export const useKbDocuments = (id: string, p: ListParams<DocumentFilters>, polling = false) =>
  useQuery({ queryKey: kk.documents(id, p), queryFn: () => api.knowledge.kbs.documents(id, p), ...paged, refetchInterval: pollWhile(polling) });
export const useSourcesList = (p: ListParams<SourceFilters>) =>
  useQuery({ queryKey: kk.sources(p), queryFn: () => api.knowledge.sources.list(p), ...paged, refetchInterval: (q) => pollWhile(!!q.state.data?.data.some((s) => s.running)) });
export const useSource = (id: string) =>
  useQuery({ queryKey: kk.source(id), queryFn: () => api.knowledge.sources.get(id), refetchInterval: (q) => pollWhile(!!q.state.data?.running) });
export const useSourceItems = (id: string, p: ListParams<ItemFilters>, polling = false) =>
  useQuery({
    queryKey: kk.items(id, p),
    queryFn: () => api.knowledge.sources.items(id, p),
    ...paged,
    refetchInterval: (q) => pollWhile(polling || !!q.state.data?.data.some((i) => i.status === 'processing' || i.status === 'pending')),
  });
export const useSourceRuns = (id: string, p: ListParams<RunFilters>) =>
  useQuery({ queryKey: kk.runs(id, p), queryFn: () => api.knowledge.sources.runs(id, p), ...paged, refetchInterval: (q) => pollWhile(!!q.state.data?.data.some((r) => r.status === 'running')) });
export const useSyncRun = (id: string | null) =>
  useQuery({ queryKey: kk.run(id ?? ''), queryFn: () => api.knowledge.sources.run(id!), enabled: !!id, refetchInterval: (q) => pollWhile(q.state.data?.status === 'running') });
export const useItem = (id: string | null) =>
  useQuery({ queryKey: kk.item(id ?? ''), queryFn: () => api.knowledge.items.get(id!), enabled: !!id, refetchInterval: (q) => pollWhile(q.state.data?.status === 'processing') });
/** Seeded documents for the split preview; a source's own documents come first. */
export const useIngestSamples = (sourceId?: string) => useQuery({ queryKey: kk.samples(sourceId), queryFn: () => api.knowledge.sources.samples(sourceId), staleTime: 60_000 });
export const useKnowledgeLookups = () => useQuery({ queryKey: kk.lookups, queryFn: api.knowledge.lookups, staleTime: 60_000 });

/** Knowledge base names are agent collections, so writes also refresh the shared lookups and agent pages. */
function useWrite<A, R>(fn: (a: A) => Promise<R>, alsoRoots: string[] = []) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(['knowledge', ...alsoRoots].map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}

export const useCreateKb = () => useWrite((i: KnowledgeBaseInput) => api.knowledge.kbs.create(i), ['lookups']);
export const useUpdateKb = (id: string) => useWrite((p: KnowledgeBasePatch) => api.knowledge.kbs.update(id, p), ['lookups']);
export const useDeleteKb = () => useWrite((id: string) => api.knowledge.kbs.remove(id), ['lookups']);
export const useDuplicateKb = () => useWrite((id: string) => api.knowledge.kbs.duplicate(id), ['lookups']);
export const useRefreshKb = () => useWrite((id: string) => api.knowledge.kbs.refresh(id));
export const useCancelKbJob = () => useWrite((id: string) => api.knowledge.kbs.cancelJob(id));
export const useRetryKbFailed = () => useWrite((id: string) => api.knowledge.kbs.retryFailed(id));
export const useAttachSources = (id: string) => useWrite((ids: string[]) => api.knowledge.kbs.attachSources(id, ids));
export const useDetachSource = (id: string) => useWrite((sourceId: string) => api.knowledge.kbs.detachSource(id, sourceId));
export const useSetKbSourceRules = (id: string) => useWrite(({ sourceId, rules }: { sourceId: string; rules: Rule[] }) => api.knowledge.kbs.setSourceRules(id, sourceId, rules));
export const useBulkRefreshKbs = () => useWrite((ids: string[]) => api.knowledge.kbs.bulkRefresh(ids));
export const useBulkDeleteKbs = () => useWrite((ids: string[]) => api.knowledge.kbs.bulkRemove(ids), ['lookups']);
export const useKbQuery = (id: string) => useMutation({ mutationFn: (i: QueryInput) => api.knowledge.kbs.query(id, i) });
/** Search across several knowledge bases, as chat and workflow knowledge steps do. */
export const useRetrieve = () => useMutation({ mutationFn: (i: RetrieveInput) => api.knowledge.retrieve(i) });
/** Splits a sample document with draft settings; nothing is saved. */
export const usePreviewSplit = () => useMutation({ mutationFn: (i: SplitPreviewInput) => api.knowledge.sources.previewSplit(i) });

export const useCreateSource = () =>
  useWrite(({ input, sync, kbIds }: { input: SourceInput; sync?: boolean; kbIds?: string[] }) => api.knowledge.sources.create(input, { sync, kbIds }));
export const useUpdateSource = (id: string) => useWrite((p: SourcePatch) => api.knowledge.sources.update(id, p));
export const useDeleteSource = () => useWrite((id: string) => api.knowledge.sources.remove(id));
export const useSyncSource = () => useWrite(({ id, opts }: { id: string; opts?: SyncOptions }) => api.knowledge.sources.sync(id, opts));
export const useCancelRun = () => useWrite((id: string) => api.knowledge.sources.cancelRun(id));
export const usePauseSource = () => useWrite(({ id, paused }: { id: string; paused: boolean }) => api.knowledge.sources.setPaused(id, paused));
export const useReprocessSource = () => useWrite((id: string) => api.knowledge.sources.reprocess(id));
export const usePreviewHeld = () => useMutation({ mutationFn: (i: HeldPreviewInput) => api.knowledge.sources.previewHeld(i) });
export const usePreviewSource = () => useMutation({ mutationFn: (i: Pick<SourceInput, 'type' | 'config'>) => api.knowledge.sources.preview(i) });
export const useApproveIngest = () => useWrite((id: string) => api.knowledge.sources.approveIngest(id));
export const useBulkSyncSources = () => useWrite((ids: string[]) => api.knowledge.sources.bulkSync(ids));
export const useBulkPauseSources = () => useWrite(({ ids, paused }: { ids: string[]; paused: boolean }) => api.knowledge.sources.bulkSetPaused(ids, paused));
export const useBulkDeleteSources = () => useWrite((ids: string[]) => api.knowledge.sources.bulkRemove(ids));

export const useReprocessItems = () => useWrite((ids: string[]) => api.knowledge.items.reprocess(ids));
export const useExcludeItems = () => useWrite((ids: string[]) => api.knowledge.items.exclude(ids));
export const useVerifyItem = () => useWrite(({ id, verified }: { id: string; verified: boolean }) => api.knowledge.items.verify(id, verified));
export const useSetItemTags = () => useWrite(({ id, tags }: { id: string; tags: string[] }) => api.knowledge.items.setTags(id, tags));
export const useSetItemOwner = () => useWrite(({ id, owner }: { id: string; owner: string }) => api.knowledge.items.setOwner(id, owner));
export const useSetItemMetadata = () => useWrite(({ id, values }: { id: string; values: Record<string, string> }) => api.knowledge.items.setMetadata(id, values));
export const useTagItems = () => useWrite(({ ids, tag }: { ids: string[]; tag: string }) => api.knowledge.items.addTag(ids, tag));
