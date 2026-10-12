import type { ListParams } from '@/lib/types/query';

import type { WikiApi } from './wiki-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for the Wiki; `get`, `send` and `qs` come from the main HTTP client. */
export function createWikiHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): WikiApi {
  return {
    list: (p) => get(`/wiki/pages?${qs(p)}`),
    get: (id) => get(`/wiki/pages/${id}`),
    verify: (id) => send('POST', `/wiki/pages/${id}/verify`),
    collections: () => get('/wiki/collections'),
  };
}
