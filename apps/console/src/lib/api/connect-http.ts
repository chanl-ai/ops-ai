import type { ConnectApi } from './connect-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for the Connect page; `get` and `send` come from the main HTTP client. */
export function createConnectHttp(get: Get, send: Send): ConnectApi {
  return {
    get: (p) => get(`/connect?range=${p.range}`),
    setExposed: (wid, audience, exposed) => send('PUT', `/connect/tools/${wid}/${audience}`, { exposed }),
    recordCopy: () => send('POST', '/connect/journey/copied'),
    saveSettings: (i) => send('PUT', '/connect/settings', i),
  };
}
