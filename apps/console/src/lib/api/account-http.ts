import type { ListParams } from '@/lib/types/query';

import type { AccountApi } from './account-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for the signed-in person's account; `get`, `send` and `qs` come from the main HTTP client. */
export function createAccountHttp(get: Get, send: Send, qs: (p: ListParams) => string): AccountApi {
  return {
    profile: () => get('/account'),
    updateProfile: (i) => send('PATCH', '/account', i),
    changePassword: (i) => send('POST', '/account/password', i),
    mfa: {
      list: () => get('/account/mfa'),
      regenerateCodes: () => send('POST', '/account/mfa/recovery-codes'),
      remove: (id) => send('DELETE', `/account/mfa/${encodeURIComponent(id)}`),
    },
    sessions: {
      list: (p) => get(`/account/sessions?${qs(p)}`),
      revoke: (id) => send('DELETE', `/account/sessions/${encodeURIComponent(id)}`),
      revokeOthers: () => send('POST', '/account/sessions/revoke-others'),
    },
  };
}
