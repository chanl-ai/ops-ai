import type { AuthKind } from '@/lib/types/connections';

import type { ConnectionsApi } from './connections-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** tools-service's `/connections`, `/connection-kinds` and `/me/connections` routes (c-558). */
export function createConnectionsHttp(get: Get, send: Send): ConnectionsApi {
  const one = (id: string) => `/connections/${encodeURIComponent(id)}`;
  return {
    get: (id) => get(one(id)),
    kinds: async () => (await get<{ kinds: AuthKind[] }>('/connection-kinds')).kinds,
    setSignIn: (id, i) => send('PATCH', one(id), i),
    test: (id, i) => send('POST', `${one(id)}/test`, i),
    startSignIn: (id, i) => send('POST', `${one(id)}/sign-in`, i),
    completeSignIn: (id, i) => send('POST', `${one(id)}/sign-in/complete`, i),
    openConnectLink: (link) => send('POST', '/connections/connect-links/sign-in', { link }),
    mine: () => get('/me/connections'),
    disconnect: (id, environment) => send('DELETE', `/me/connections/${encodeURIComponent(id)}?environment=${environment}`),
  };
}
