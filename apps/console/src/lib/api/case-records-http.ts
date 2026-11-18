import type { CaseRecordsApi } from './case-records-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** On the agents service's `/v1` transport. Lists repeat a parameter per value, as the API reads them. */
export function createCaseRecordsHttp(get: Get, send: Send): CaseRecordsApi {
  return {
    get: (id) => get(`/cases/${encodeURIComponent(id)}`),
    change: (id, patch) => send('PATCH', `/cases/${encodeURIComponent(id)}`, patch),
    addNote: (id, text) => send('POST', `/cases/${encodeURIComponent(id)}/events`, { kind: 'note', text }),
  };
}
