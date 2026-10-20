import type { ListParams } from '@/lib/types/query';

import type { EgressApi } from './egress-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;
type Qs = (p: ListParams) => string;

const plural = { host: 'hosts', range: 'ranges' } as const;

/** tools-service's `/egress` routes; removal is a POST to `.../remove`, as the service defines it. */
export function createEgressHttp(get: Get, send: Send, qs: Qs): EgressApi {
  return {
    list: () => get('/egress'),
    hosts: (p) => get(`/egress/hosts?${qs(p)}`),
    add: (kind, value, note) => send('POST', `/egress/${plural[kind]}`, { value, note }),
    remove: (kind, value) => send('POST', `/egress/${plural[kind]}/remove`, { value }),
  };
}
