import type { ListParams } from '@/lib/types/query';

import type { AssuranceApi } from './assurance-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for Assurance; `get`, `send` and `qs` come from the main HTTP client. */
export function createAssuranceHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): AssuranceApi {
  return {
    list: (p) => get(`/assurance/${p.tab}?${qs(p)}`),
    exportBundle: (id) => send('POST', `/assurance/evidence/${id}/export`),
  };
}
