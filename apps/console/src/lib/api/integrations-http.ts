import type { ListParams } from '@/lib/types/query';

import type { IntegrationsApi } from './integrations-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for integrations; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createIntegrationsHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): IntegrationsApi {
  const base = '/integrations';
  return {
    list: (p) => get(`${base}?${qs(p)}`),
    get: (id) => get(`${base}/${id}`),
    options: () => get(`${base}/options`),
    catalog: () => get(`${base}/catalog`),
    connect: (i) => send('POST', base, i),
    reconnect: (id) => send('POST', `${base}/${id}/reconnect`),
    rotate: (id, credentialRef) => send('PATCH', `${base}/${id}/credential`, { credentialRef }),
    check: (id) => send('POST', `${base}/${id}/check`),
    bulkCheck: (ids) => send('POST', `${base}/bulk-check`, { ids }),
    impact: (ids) => send('POST', `${base}/impact`, { ids }),
    revoke: (ids, reason) => send('POST', `${base}/revoke`, { ids, reason }),
    requestScopes: (id, i) => send('POST', `${base}/${id}/scope-requests`, i),
  };
}
