import type { ListParams } from '@/lib/types/query';

import type { KnowledgeApi } from './knowledge-contract';
import { optionsQs } from './options';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for knowledge; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createKnowledgeHttp(get: Get, send: Send, qs: (p: ListParams) => string): KnowledgeApi {
  return {
    kbs: {
      list: (p) => get(`/knowledge-bases?${qs(p)}`),
      options: (p) => get(`/knowledge-bases/options?${optionsQs(p)}`),
      get: (id) => get(`/knowledge-bases/${id}`),
      create: (i) => send('POST', '/knowledge-bases', i),
      update: (id, patch) => send('PATCH', `/knowledge-bases/${id}`, patch),
      remove: (id) => send('DELETE', `/knowledge-bases/${id}`),
      duplicate: (id) => send('POST', `/knowledge-bases/${id}/duplicate`),
      refresh: (id) => send('POST', `/knowledge-bases/${id}/refresh`),
      cancelJob: (id) => send('POST', `/knowledge-bases/${id}/refresh/cancel`),
      retryFailed: (id) => send('POST', `/knowledge-bases/${id}/retry-failed`),
      attachSources: (id, sourceIds) => send('POST', `/knowledge-bases/${id}/sources`, { sourceIds }),
      detachSource: (id, sourceId) => send('DELETE', `/knowledge-bases/${id}/sources/${sourceId}`),
      setSourceRules: (id, sourceId, rules) => send('PUT', `/knowledge-bases/${id}/sources/${sourceId}/rules`, { rules }),
      documents: (id, p) => get(`/knowledge-bases/${id}/documents?${qs(p)}`),
      query: (id, i) => send('POST', `/knowledge-bases/${id}/query`, i),
      addPage: (id, i) => send('POST', `/knowledge-bases/${id}/pages`, i),
      addDocuments: (id, fileIds) => send('POST', `/knowledge-bases/${id}/documents`, { fileIds }),
      bulkRefresh: (ids) => send('POST', '/knowledge-bases/bulk-refresh', { ids }),
      bulkRemove: (ids) => send('POST', '/knowledge-bases/bulk-delete', { ids }),
    },
    sources: {
      list: (p) => get(`/sources?${qs(p)}`),
      get: (id) => get(`/sources/${id}`),
      create: (i, opts) => send('POST', '/sources', { ...i, ...opts }),
      update: (id, patch) => send('PATCH', `/sources/${id}`, patch),
      remove: (id) => send('DELETE', `/sources/${id}`),
      sync: (id, opts) => send('POST', `/sources/${id}/sync`, opts),
      addFiles: (id, fileIds) => send('POST', `/sources/${id}/files`, { fileIds }),
      putItem: (id, input) => send('POST', `/sources/${id}/items`, input),
      cancelRun: (runId) => send('POST', `/sync-runs/${runId}/cancel`),
      setPaused: (id, paused) => send('POST', `/sources/${id}/${paused ? 'pause' : 'resume'}`),
      tombstones: (id) => get(`/sources/${id}/tombstones`),
      liftTombstones: (id, ids) => send('POST', `/sources/${id}/tombstones/lift`, { ids }),
      items: (id, p) => get(`/sources/${id}/items?${qs(p)}`),
      runs: (id, p) => get(`/sources/${id}/runs?${qs(p)}`),
      run: (runId) => get(`/sync-runs/${runId}`),
      preview: (config) => send('POST', '/sources/preview', { config }),
      scopes: (input) => send('POST', '/sources/scopes', input),
      previewHeld: (i) => send('POST', '/sources/preview-held', i),
      samples: (sourceId) => get(`/ingest/samples${sourceId ? `?sourceId=${sourceId}` : ''}`),
      previewSplit: (i) => send('POST', '/ingest/preview-split', i),
      aiEstimate: (id) => get(`/sources/${id}/ai-estimate`),
      decideAiSteps: (id, decision) => send('POST', `/sources/${id}/ai-approval`, { decision }),
      bulkSync: (ids) => send('POST', '/sources/bulk-sync', { ids }),
      bulkSetPaused: (ids, paused) => send('POST', '/sources/bulk-pause', { ids, paused }),
      bulkRemove: (ids) => send('POST', '/sources/bulk-delete', { ids }),
    },
    items: {
      get: (id) => get(`/items/${id}`),
      reprocess: (ids) => send('POST', '/items/reprocess', { ids }),
      exclude: (ids) => send('POST', '/items/exclude', { ids }),
      verify: (id, verified) => send('POST', `/items/${id}/verify`, { verified }),
      setTags: (id, tags) => send('PUT', `/items/${id}/tags`, { tags }),
      setOwner: (id, owner) => send('PUT', `/items/${id}/owner`, { owner }),
      addTag: (ids, tag) => send('POST', '/items/tag', { ids, tag }),
      setMetadata: (id, values) => send('PATCH', `/items/${id}/metadata`, { values }),
    },
    sourceKinds: () => get('/data/knowledge/source-kinds'),
    lookups: () => get('/data/knowledge/lookups'),
  };
}
