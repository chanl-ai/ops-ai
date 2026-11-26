import type { ListParams } from '@/lib/types/query';

import type { ProviderConnectionsApi } from './provider-connections-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** models-service's `/models/providers` routes. */
export function createProviderConnectionsHttp(get: Get, send: Send, qs: (p: ListParams) => string): ProviderConnectionsApi {
  return {
    list: (p) => get(`/models/providers?${qs(p)}`),
    create: (input) => send('POST', '/models/providers', input),
    types: () => get('/models/provider-types'),
    catalog: (providerId) => get(`/models/providers/${encodeURIComponent(providerId)}/catalog`),
  };
}
