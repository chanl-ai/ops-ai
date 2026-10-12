import type { SecretsApi } from './secrets-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** tools-service's `/secrets` routes. */
export function createSecretsHttp(get: Get, send: Send): SecretsApi {
  return {
    list: () => get('/secrets'),
    create: (name, value) => send('POST', '/secrets', { name, value }),
    rotate: (name, value) => send('POST', `/secrets/${encodeURIComponent(name)}/rotate`, { value }),
    remove: (name) => send('DELETE', `/secrets/${encodeURIComponent(name)}`),
  };
}
