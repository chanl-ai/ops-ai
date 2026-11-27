import type { ListParams } from '@/lib/types/query';

import type { ProviderKeysApi } from './provider-keys-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** models-service's `/provider-keys` routes. */
export function createProviderKeysHttp(get: Get, send: Send, qs: (p: ListParams) => string): ProviderKeysApi {
  return {
    list: (p) => get(`/provider-keys?${qs(p)}`),
    save: (name, value) => send('PUT', `/provider-keys/${encodeURIComponent(name)}`, { value }),
    remove: (name) => send('DELETE', `/provider-keys/${encodeURIComponent(name)}`),
    check: (name, where) => send('POST', `/provider-keys/${encodeURIComponent(name)}/check`, where),
    models: (name, where) => get(`/provider-keys/${encodeURIComponent(name)}/models?${new URLSearchParams(Object.entries(where).filter(([, v]) => !!v) as [string, string][])}`),
  };
}
