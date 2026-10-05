import type { ListParams } from '@/lib/types/query';

import type { KnowledgeApi } from './knowledge-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for knowledge; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createKnowledgeHttp(get: Get, send: Send, qs: (p: ListParams) => string): KnowledgeApi {
  return {
    kbs: {
      list: (p) => get(`/knowledge-bases?${qs(p)}`),
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
      cancelRun: (id) => send('POST', `/sources/${id}/sync/cancel`),
      setPaused: (id, paused) => send('POST', `/sources/${id}/${paused ? 'pause' : 'resume'}`),
      reprocess: (id) => send('POST', `/sources/${id}/reprocess`),
      items: (id, p) => get(`/sources/${id}/items?${qs(p)}`),
      runs: (id, p) => get(`/sources/${id}/runs?${qs(p)}`),
      run: (runId) => get(`/sync-runs/${runId}`),
      preview: (i) => send('POST', '/sources/preview', i),
      connections: () => get('/connections'),
      connect: (type) => send('POST', '/connections', { type }),
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
    },
    lookups: () => get('/knowledge/lookups'),
  };
}
