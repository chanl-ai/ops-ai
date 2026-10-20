import type { SignInProvidersApi } from './sign-in-providers-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** platform-service's sign-in provider routes (/v1/settings/sign-in/…, c-188 and c-195). */
export function createSignInProvidersHttp(get: Get, send: Send): SignInProvidersApi {
  return {
    list: () => get('/settings/sign-in/providers'),
    save: (id, input) => send('PUT', `/settings/sign-in/providers/${encodeURIComponent(id)}`, input),
    remove: (id) => send('DELETE', `/settings/sign-in/providers/${encodeURIComponent(id)}`),
    verifyDomain: (domain) => send('POST', `/settings/sign-in/domains/${encodeURIComponent(domain)}/verify`),
    secretNames: () => get('/settings/sign-in/secret-names'),
  };
}
