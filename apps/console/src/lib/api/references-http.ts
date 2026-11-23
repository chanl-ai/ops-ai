import type { ReferenceContext } from '@/lib/types/references';

import type { ReferencesApi } from './references-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: 'POST', path: string, body: unknown) => Promise<T>;

const query = (context: ReferenceContext, rest: [string, string][]) => new URLSearchParams([...Object.entries(context), ...rest]).toString();

/** agents-service's `/v1/references`; `get` comes from a transport rooted at `/v1`. */
export function createReferencesHttp(get: Get, send: Send): ReferencesApi {
  return {
    search: (context, p) => {
      const rest: [string, string][] = [['search', p.search]];
      if (p.kind) rest.push(['kind', p.kind]);
      if (p.kind && p.cursor) rest.push(['cursor', p.cursor]);
      if (p.limit) rest.push(['limit', String(p.limit)]);
      return get(`/references?${query(context, rest)}`);
    },
    labels: (context, ids) => get(`/references?${query(context, ids.map((id) => ['ids', id]))}`),
    add: (agentId, ref) => send('POST', `/agents/${agentId}/references`, ref),
  };
}
