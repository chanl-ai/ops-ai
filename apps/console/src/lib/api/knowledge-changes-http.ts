import type { ListParams } from '@/lib/types/query';

import type { KnowledgeChangesApi } from './knowledge-changes-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for knowledge change review; `get`, `send` and `qs` come from the main HTTP client. */
export function createKnowledgeChangesHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): KnowledgeChangesApi {
  return {
    list: (p) => get(`/knowledge-changes?${qs(p)}${p.kbId ? `&kbId=${encodeURIComponent(p.kbId)}` : ''}`),
    get: (id) => get(`/knowledge-changes/${id}`),
    decide: (input) => send('POST', '/knowledge-changes/decide', input),
    edit: (id, pair) => send('PATCH', `/knowledge-changes/${id}`, pair),
  };
}
