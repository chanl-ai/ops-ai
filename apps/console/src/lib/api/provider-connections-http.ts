import type { ProviderConnectionsApi } from './provider-connections-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** models-service's `/models/providers` routes. */
export function createProviderConnectionsHttp(get: Get, send: Send): ProviderConnectionsApi {
  return {
    list: () => get('/models/providers'),
    create: (input) => send('POST', '/models/providers', input),
  };
}
