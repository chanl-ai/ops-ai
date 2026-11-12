import type { OAuthApi } from './oauth-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** platform-service's /v1/oauth routes for the consent page and the person's own connections. */
export function createOAuthHttp(get: Get, send: Send): OAuthApi {
  return {
    consent: (request) => get(`/oauth/consent?${new URLSearchParams(request)}`),
    // response_type belongs to the redirect that brought the browser here; the answer names the rest of the request.
    decide: (request, decision) => {
      const { response_type: _kind, ...rest } = request;
      return send('POST', '/oauth/consent', { ...rest, decision });
    },
    grants: () => get('/oauth/grants'),
    disconnect: (id) => send('DELETE', `/oauth/grants/${encodeURIComponent(id)}`),
  };
}
