import type { InvitesApi } from './invites-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** Public invite routes; `get` and `send` come from the main HTTP client. */
export function createInvitesHttp(get: Get, send: Send): InvitesApi {
  return {
    get: (token) => get(`/invites/${encodeURIComponent(token)}`),
    accept: (token, input) => send('POST', `/invites/${encodeURIComponent(token)}/accept`, input),
  };
}
