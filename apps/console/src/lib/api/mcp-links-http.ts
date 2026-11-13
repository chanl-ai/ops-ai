import type { McpLinksApi } from './mcp-links-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** tools-service's `/v1/mcp-links`; `get` and `send` come from a transport rooted at `/v1`. */
export function createMcpLinksHttp(get: Get, send: Send): McpLinksApi {
  return {
    list: () => get('/mcp-links'),
    get: (id) => get(`/mcp-links/${encodeURIComponent(id)}`),
    create: (input) => send('POST', '/mcp-links', input),
    setPaused: (id, paused) => send('PATCH', `/mcp-links/${encodeURIComponent(id)}`, { paused }),
  };
}
