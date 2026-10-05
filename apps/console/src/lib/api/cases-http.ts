import type { ListParams } from '@/lib/types/query';

import type { CasesApi } from './cases-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for cases; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createCasesHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): CasesApi {
  return {
    list: (p) => get(`/cases?${qs(p)}`),
    get: (id) => get(`/cases/${id}`),
    setField: (id, key, value) => send('PATCH', `/cases/${id}/fields/${encodeURIComponent(key)}`, { value }),
    assign: (ids, assignee) => send('POST', '/cases/assign', { ids, assignee }),
    close: (ids, reason) => send('POST', '/cases/close', { ids, reason }),
    decideAction: (caseId, actionId, input) => send('POST', `/cases/${caseId}/actions/${actionId}/decision`, input),
    editAction: (caseId, actionId, input) => send('PATCH', `/cases/${caseId}/actions/${actionId}`, { input }),
    testSampleMail: (config, input) => send('POST', '/email-workflows/test', { config, input }),
    queues: () => get('/cases/queues'),
  };
}
