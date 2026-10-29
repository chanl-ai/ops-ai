import type { ProviderKeysApi } from './provider-keys-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** models-service's `/provider-keys` routes. */
export function createProviderKeysHttp(get: Get, send: Send): ProviderKeysApi {
  return {
    list: () => get('/provider-keys'),
    save: (name, value) => send('PUT', `/provider-keys/${encodeURIComponent(name)}`, { value }),
    remove: (name) => send('DELETE', `/provider-keys/${encodeURIComponent(name)}`),
  };
}
