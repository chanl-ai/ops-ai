import type { ReferenceContext } from '@/lib/types/references';

import type { ReferencesApi } from './references-contract';

type Get = <T>(path: string) => Promise<T>;

const query = (context: ReferenceContext, rest: [string, string][]) => new URLSearchParams([...Object.entries(context), ...rest]).toString();

/** agents-service's `/v1/references`; `get` comes from a transport rooted at `/v1`. */
export function createReferencesHttp(get: Get): ReferencesApi {
  return {
    search: (context, p) => get(`/references?${query(context, [['search', p.search], ...(p.kind ? ([['kind', p.kind]] as [string, string][]) : []), ...(p.limit ? ([['limit', String(p.limit)]] as [string, string][]) : [])])}`),
    labels: (context, ids) => get(`/references?${query(context, ids.map((id) => ['ids', id]))}`),
  };
}
