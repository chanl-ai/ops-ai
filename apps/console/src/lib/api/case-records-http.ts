import type { CaseRecordsApi } from './case-records-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** On the agents service's `/v1` transport. Lists repeat a parameter per value, as the API reads them. */
export function createCaseRecordsHttp(get: Get, send: Send): CaseRecordsApi {
  return {
    list: ({ page, pageSize, search, status, priority, assignee, overdue }) => {
      const q = new URLSearchParams({ page: String(page), pageSize: String(pageSize) });
      for (const s of status ?? []) q.append('status', s);
      for (const p of priority ?? []) q.append('priority', p);
      if (search) q.set('search', search);
      if (assignee) q.set('assignee', assignee);
      if (overdue) q.set('overdue', 'true');
      return get(`/cases?${q}`);
    },
    get: (id) => get(`/cases/${encodeURIComponent(id)}`),
    change: (id, patch) => send('PATCH', `/cases/${encodeURIComponent(id)}`, patch),
    addNote: (id, text) => send('POST', `/cases/${encodeURIComponent(id)}/events`, { kind: 'note', text }),
  };
}
