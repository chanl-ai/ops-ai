import type { SignInPolicyApi } from './sign-in-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for the sign-in policy; `get` and `send` come from the main HTTP client so auth and envelopes match. */
export function createSignInPolicyHttp(get: Get, send: Send): SignInPolicyApi {
  return {
    get: () => get('/settings/sign-in'),
    save: (patch) => send('PATCH', `/settings/sign-in/${patch.section}`, patch),
    addDomain: (domain) => send('POST', '/settings/sign-in/domains', { domain }),
    verifyDomain: (domain) => send('POST', `/settings/sign-in/domains/${encodeURIComponent(domain)}/verify`),
    removeDomain: (domain) => send('DELETE', `/settings/sign-in/domains/${encodeURIComponent(domain)}`),
    testConnection: () => send('POST', '/settings/sign-in/sso/test'),
  };
}
