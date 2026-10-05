import type { ListParams } from '@/lib/types/query';

import type { GovernanceApi } from './governance-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for logs and access; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createGovernanceHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): GovernanceApi {
  return {
    toolCalls: {
      list: (p) => get(`/logs/tool-calls?${qs(p)}`),
      get: (id) => get(`/logs/tool-calls/${id}`),
    },
    audit: {
      list: (p) => get(`/logs/audit?${qs(p)}`),
    },
    access: {
      identities: (p) => get(`/access/identities?${qs(p)}`),
      grants: (p) => get(`/access/grants?${qs(p)}`),
      grant: (i) => send('POST', '/access/grants', i),
      revoke: (ids, reason) => send('POST', '/access/grants/revoke', { ids, reason }),
      extend: (ids, days) => send('POST', '/access/grants/extend', { ids, days }),
      roles: (p) => get(`/access/roles?${qs(p)}`),
      assignRole: (i) => send('POST', '/access/roles', i),
      removeRoles: (ids) => send('POST', '/access/roles/delete', { ids }),
      options: () => get('/access/options'),
    },
  };
}
