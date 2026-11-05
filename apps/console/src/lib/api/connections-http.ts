import type { AccountRef, AuthKind } from '@/lib/types/connections';

import type { ConnectionsApi } from './connections-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** tools-service's account sign-in routes under `/apps`, `/connection-kinds`, `/connect-links` and `/me/accounts`. */
export function createConnectionsHttp(get: Get, send: Send): ConnectionsApi {
  const one = (a: AccountRef) => `/apps/${encodeURIComponent(a.appId)}/accounts/${encodeURIComponent(a.accountId)}`;
  const mine = (id: string) => `/me/accounts/${encodeURIComponent(id)}`;
  return {
    kinds: async () => (await get<{ kinds: AuthKind[] }>('/connection-kinds')).kinds,
    startSignIn: (a, i) => send('POST', `${one(a)}/sign-in`, i),
    finishSignIn: (i) => send('POST', '/sign-ins/complete', i),
    openConnectLink: (link) => send('POST', '/connect-links/sign-in', { link }),
    mine: (every) => get(every ? '/me/accounts?every=true' : '/me/accounts'),
    giveOwn: (id, i) => send('PUT', `${mine(id)}/credentials`, i),
    disconnect: (id) => send('DELETE', mine(id)),
    startCredentialCheck: (a) => send('POST', `${one(a)}/test-credential`, {}),
  };
}
