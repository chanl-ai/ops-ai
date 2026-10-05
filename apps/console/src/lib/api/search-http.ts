import type { SearchApi } from './search-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for palette search; `get` and `send` come from the main HTTP client. */
export function createSearchHttp(get: Get, send: Send): SearchApi {
  return {
    query: (q) => get(`/search?q=${encodeURIComponent(q)}`),
    recent: () => get('/search/recent'),
    visit: (hit) => send('POST', '/search/recent', hit),
  };
}
