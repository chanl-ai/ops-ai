import type { ActivityApi } from './activity-contract';

type Get = <T>(path: string) => Promise<T>;

/** On the agents service's `/v1` transport; each filter repeats its parameter per value, as the API reads them. */
export function createActivityHttp(get: Get): ActivityApi {
  return {
    list: ({ page, pageSize, kind, status, source }) => {
      const q = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
      for (const k of kind ?? []) q.append('kind', k);
      for (const s of status ?? []) q.append('status', s);
      for (const s of source ?? []) q.append('source', s);
      return get(`/activity?${q}`);
    },
  };
}
