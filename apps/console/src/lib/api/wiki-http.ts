import type { ListParams } from '@/lib/types/query';

import type { WikiApi } from './wiki-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for the Wiki; `get`, `send` and `qs` come from the main HTTP client. */
export function createWikiHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): WikiApi {
  return {
    list: (p) => get(`/data/wiki/pages?${qs(p)}`),
    get: (id) => get(`/data/wiki/pages/${id}`),
    verify: (id) => send('POST', `/data/wiki/pages/${id}/verify`),
    collections: () => get('/data/wiki/collections'),
    collectionsPage: (p) => get(`/data/wiki/collections?${qs(p)}`),
  };
}
