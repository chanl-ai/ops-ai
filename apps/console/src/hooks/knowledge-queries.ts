'use client';

import { keepPreviousData, useMutation, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import { sdk } from '@/lib/api/ops-sdk';
import type {
  DocumentFilters,
  ItemFilters,
  KbFilters,
  KnowledgeBaseInput,
  KnowledgeBasePatch,
  QueryInput,
  RunFilters,
  SourceFilters,
  ScopesInput,
  SourceInput,
  SourcePatch,
  SyncOptions,
  WrittenItemInput,
} from '@/lib/types/knowledge';
import type { ListParams } from '@/lib/types/query';
import { useServerList } from './server-list';
import { useTeamQuery } from './team-query';
import { useDebounced } from './use-debounced';

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
  tombstones: (id: string) => ['knowledge', 'source', id, 'tombstones'] as const,
  aiEstimate: (id: string) => ['knowledge', 'source', id, 'ai-estimate'] as const,
  item: (id: string) => ['knowledge', 'item', id] as const,
  itemText: (id: string) => ['knowledge', 'item', id, 'text'] as const,
  lookups: ['knowledge', 'lookups'] as const,
  sourceKinds: ['knowledge', 'source-kinds'] as const,
};

/** While an index refresh or sync runs, poll so progress moves without a reload. */
const POLL_MS = 1500;
const pollWhile = (running: boolean) => (running ? POLL_MS : false);

export const useKnowledgeBases = (p: ListParams<KbFilters>) =>
  usePagedQuery({ queryKey: kk.kbs(p), queryFn: () => api.knowledge.kbs.list(p), refetchInterval: (q) => pollWhile(!!q.state.data?.data.some((k) => k.indexing)) });
export const useKnowledgeBase = (id: string) =>
  useTeamQuery({ queryKey: kk.kb(id), queryFn: () => api.knowledge.kbs.get(id), refetchInterval: (q) => pollWhile(!!q.state.data?.indexing || !!q.state.data?.attached.some((a) => a.running)) });
export const useAddPage = (id: string) => useWrite((i: { title: string; text: string }) => api.knowledge.kbs.addPage(id, i));
export const useAddDocuments = (id: string) => useWrite((fileIds: string[]) => api.knowledge.kbs.addDocuments(id, fileIds), ['files']);
export const useKbDocuments = (id: string, p: ListParams<DocumentFilters>, polling = false) =>
  usePagedQuery({ queryKey: kk.documents(id, p), queryFn: () => api.knowledge.kbs.documents(id, p), refetchInterval: pollWhile(polling) });
export const useSourcesList = (p: ListParams<SourceFilters>) =>
  usePagedQuery({ queryKey: kk.sources(p), queryFn: () => api.knowledge.sources.list(p), refetchInterval: (q) => pollWhile(!!q.state.data?.data.some((s) => s.running)) });
export const useSource = (id: string, enabled = true) =>
  useTeamQuery({ queryKey: kk.source(id), queryFn: () => api.knowledge.sources.get(id), enabled: enabled && !!id, refetchInterval: (q) => pollWhile(!!q.state.data?.running) });
export const useSourceItems = (id: string, p: ListParams<ItemFilters>, polling = false) =>
  usePagedQuery({
    queryKey: kk.items(id, p),
    queryFn: () => api.knowledge.sources.items(id, p),
    refetchInterval: (q) => pollWhile(polling || !!q.state.data?.data.some((i) => i.status === 'processing' || i.status === 'pending')),
  });
export const useSourceRuns = (id: string, p: ListParams<RunFilters>) =>
  usePagedQuery({ queryKey: kk.runs(id, p), queryFn: () => api.knowledge.sources.runs(id, p), refetchInterval: (q) => pollWhile(!!q.state.data?.data.some((r) => r.status === 'running')) });
export const useSyncRun = (id: string | null) =>
  useTeamQuery({ queryKey: kk.run(id ?? ''), queryFn: () => api.knowledge.sources.run(id!), enabled: !!id, refetchInterval: (q) => pollWhile(q.state.data?.status === 'running') });
/** A document's pieces matching `search`, a page at a time from GET /v1/items/{id}/chunks: a long document is never loaded whole to search it. */
export const useItemPieces = (id: string | undefined, search: string, enabled: boolean) =>
  useServerList(
    ['item-pieces', id],
    (ask) => sdk((ops) => ops.raw.kb.items_list_item_chunks({ path: { item_id: id ?? '' }, query: ask })),
    { search, enabled: enabled && !!id, pageSize: 50 },
  );
export const useItem = (id: string | null) =>
  useTeamQuery({ queryKey: kk.item(id ?? ''), queryFn: () => api.knowledge.items.get(id!), enabled: !!id, refetchInterval: (q) => pollWhile(q.state.data?.status === 'processing') });
/** What was read from an item's file, by section with page places, for the document view; asked again while the file is still being read. */
export const useItemText = (id: string) =>
  useTeamQuery({
    queryKey: kk.itemText(id),
    queryFn: () => sdk((ops) => ops.raw.kb.items_get_item_text({ path: { item_id: id } })),
    enabled: !!id,
    refetchInterval: (q) => pollWhile(q.state.data?.status === 'reading'),
  });
export const useSourceKinds = (enabled = true) => useTeamQuery({ queryKey: kk.sourceKinds, queryFn: api.knowledge.sourceKinds, enabled, staleTime: 60_000 });
/** What a website or app source with `config` would take in, before it exists; asked only while the settings are valid. */
/** What a plugin source's picker offers for `input` (a search, or what a picked parent holds). */
export const useSourceScopes = (input: ScopesInput, enabled: boolean) =>
  useTeamQuery({ queryKey: ['knowledge', 'source-scopes', input], queryFn: () => api.knowledge.sources.scopes(input), enabled, retry: false, staleTime: 60_000 });
export const useSourcePreview = (config: Record<string, unknown>, enabled: boolean) =>
  useTeamQuery({ queryKey: ['knowledge', 'source-preview', config], queryFn: () => api.knowledge.sources.preview(config), enabled, retry: false, staleTime: 60_000 });
/** The caller's team's agents citing knowledge base `kbId`, from agents-service's knowledge usage. */
/** `enabled` false for someone who may not read agents (a member), so the page asks nothing it would be refused. */
export const useAgentsCiting = (kbId: string, enabled = true) =>
  useTeamQuery({
    queryKey: ['agents', 'knowledge-usage', kbId],
    queryFn: () => sdk((ops) => ops.raw.agents.agents_knowledge_usage({ query: { ids: [kbId] } })),
    staleTime: 60_000,
    enabled,
    select: (rows) => rows.find((r) => r.kbId === kbId)?.agents ?? [],
  });
/** One kernel turn of an agent, as the Playground's answer: what the agent would say, nothing kept. */
export const useAgentTurn = () => useMutation({ mutationFn: ({ agentId, message }: { agentId: string; message: string }) => api.agents.test(agentId, message) });
export const useKnowledgeLookups = () => useTeamQuery({ queryKey: kk.lookups, queryFn: api.knowledge.lookups, staleTime: 60_000 });

/** Knowledge base names are agent collections, so writes also refresh the shared lookups and agent pages. */
function useWrite<A, R>(fn: (a: A) => Promise<R>, alsoRoots: string[] = []) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all(['knowledge', ...alsoRoots].map((r) => qc.invalidateQueries({ queryKey: [r] }))),
  });
}

// Files chosen in the create dialog are added once the base exists, so they index at once with its settings.
export const useCreateKb = () =>
  useWrite(
    async ({ input, fileIds = [] }: { input: KnowledgeBaseInput; fileIds?: string[] }) => {
      const kb = await api.knowledge.kbs.create(input);
      const added = fileIds.length ? await api.knowledge.kbs.addDocuments(kb.id, fileIds) : undefined;
      return { kb, added };
    },
    ['lookups', 'files'],
  );
export const useUpdateKb = (id: string) => useWrite((p: KnowledgeBasePatch) => api.knowledge.kbs.update(id, p), ['lookups']);
export const useDeleteKb = () => useWrite((id: string) => api.knowledge.kbs.remove(id), ['lookups']);
export const useRefreshKb = () => useWrite((id: string) => api.knowledge.kbs.refresh(id));
export const useRetryKbFailed = () => useWrite((id: string) => api.knowledge.kbs.retryFailed(id));
export const useAttachSources = (id: string) => useWrite((ids: string[]) => api.knowledge.kbs.attachSources(id, ids));
export const useDetachSource = (id: string) => useWrite((sourceId: string) => api.knowledge.kbs.detachSource(id, sourceId));
export const useKbQuery = (id: string) => useMutation({ mutationFn: (i: QueryInput) => api.knowledge.kbs.query(id, i) });
/** Search across several knowledge bases, as chat and workflow knowledge steps do. */

export const useCreateSource = () =>
  useWrite(({ input, sync, kbIds }: { input: SourceInput; sync?: boolean; kbIds?: string[] }) => api.knowledge.sources.create(input, { sync, kbIds }));
export const useUpdateSource = (id: string) => useWrite((p: SourcePatch) => api.knowledge.sources.update(id, p));
export const useDeleteSource = () => useWrite((id: string) => api.knowledge.sources.remove(id));
export const usePutSourceItem = () => useWrite(({ id, input }: { id: string; input: WrittenItemInput }) => api.knowledge.sources.putItem(id, input));
export const useAddSourceFiles = () => useWrite(({ id, fileIds }: { id: string; fileIds: string[] }) => api.knowledge.sources.addFiles(id, fileIds), ['files']);
export const useSyncSource = () => useWrite(({ id, opts }: { id: string; opts?: SyncOptions }) => api.knowledge.sources.sync(id, opts));
export const useAiEstimate = (id: string, enabled = true) => useTeamQuery({ queryKey: kk.aiEstimate(id), queryFn: () => api.knowledge.sources.aiEstimate(id), enabled });
/** Approves a new source's AI steps right after Add source creates it; refused unless the caller owns the knowledge. */
export const useApproveAiSteps = () => useWrite((id: string) => api.knowledge.sources.decideAiSteps(id, 'approve'));
export const useDecideAiSteps = (id: string) => useWrite((decision: 'approve' | 'revoke') => api.knowledge.sources.decideAiSteps(id, decision));
export const useCancelRun = () => useWrite((runId: string) => api.knowledge.sources.cancelRun(runId));
export const useTombstones = (id: string) => useTeamQuery({ queryKey: kk.tombstones(id), queryFn: () => api.knowledge.sources.tombstones(id) });
export const useLiftTombstones = (id: string) => useWrite((ids: string[]) => api.knowledge.sources.liftTombstones(id, ids));
export const usePauseSource = () => useWrite(({ id, paused }: { id: string; paused: boolean }) => api.knowledge.sources.setPaused(id, paused));

export const useVerifyItem = () => useWrite(({ id, verified }: { id: string; verified: boolean }) => api.knowledge.items.verify(id, verified));
export const useSetItemOwner = () => useWrite(({ id, owner }: { id: string; owner: string }) => api.knowledge.items.setOwner(id, owner));

/** What a screen needs of a knowledge base to name and colour it. */
export interface KbName {
  id: string;
  name: string;
  color: string;
}

/**
 * Names and colours for the knowledge bases a screen holds ids of, asked of GET /v1/knowledge-bases by `ids` (pages of
 * 50, following `hasNext`). With no ids nothing is asked: without `ids` the route returns its default page.
 */
export const useKnowledgeBaseNames = (ids: string[]) => {
  const wanted = [...new Set(ids)].sort();
  return useTeamQuery({
    queryKey: ['knowledge', 'kb-names', wanted],
    enabled: wanted.length > 0,
    staleTime: 30_000,
    queryFn: async () => {
      const found: KbName[] = [];
      for (let page = 1; ; page++) {
        const res = await sdk((ops) => ops.raw.kb.knowledge_bases_list_knowledge_bases({ query: { ids: wanted, page, pageSize: 50 } }));
        found.push(...res.data.map((k) => ({ id: k.id, name: k.name, color: k.color })));
        if (!res.pagination.hasNext) return found;
      }
    },
  });
};

/**
 * The knowledge bases whose name matches `search`, 20 at most, searched on the server once typing pauses. `within` limits
 * the search to those ids (an agent's own list); an empty `within` asks nothing.
 */
export const useKnowledgeBaseSearch = (search: string, enabled = true, within?: string[]) => {
  const text = useDebounced(search.trim(), 200);
  return useTeamQuery({
    queryKey: ['knowledge', 'kb-search', text, within ?? null],
    enabled: enabled && (!within || within.length > 0),
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<KbName[]> => {
      const res = await sdk((ops) => ops.raw.kb.knowledge_bases_list_knowledge_bases({ query: { search: text || undefined, ids: within, pageSize: 20 } }));
      return res.data.map((k) => ({ id: k.id, name: k.name, color: k.color }));
    },
  });
};
