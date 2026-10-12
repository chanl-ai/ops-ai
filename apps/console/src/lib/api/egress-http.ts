import type { EgressApi } from './egress-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

const plural = { host: 'hosts', range: 'ranges' } as const;

/** tools-service's `/egress` routes; removal is a POST to `.../remove`, as the service defines it. */
export function createEgressHttp(get: Get, send: Send): EgressApi {
  return {
    list: () => get('/egress'),
    add: (kind, value, note) => send('POST', `/egress/${plural[kind]}`, { value, note }),
    remove: (kind, value) => send('POST', `/egress/${plural[kind]}/remove`, { value }),
  };
}
