import type { ListParams } from '@/lib/types/query';

import type { RunRow } from '@/lib/types/cases';

import type { CasesApi } from './cases-contract';
import { ApiError } from './contract';

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
    runs: (p) => get(`/runs?${qs(p)}`),
    run: (id) => get(`/runs/${encodeURIComponent(id)}`),
    // Replaced by the SDK. The thread calls create and run; the stream's events are not read here because the Cases
    // row read afterwards already says how the run stopped.
    startRun: async ({ workflowId, subject, input }) => {
      const { threadId } = await send<{ threadId: string }>('POST', '/v1/threads', { graph: workflowId, metadata: { subject } });
      await send('POST', `/v1/threads/${encodeURIComponent(threadId)}/runs/stream`, { input });
      // The run has finished by now, so a 404 here means Cases does not list this graph's runs, not that it failed.
      const run = await get<RunRow>(`/runs/${encodeURIComponent(threadId)}`).catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      });
      return { threadId, run };
    },
    startable: () => get('/v1/graphs'),
    assignRuns: (ids, assignee) => send('POST', '/runs/assign', { ids, assignee }),
    queues: () => get('/cases/queues'),
  };
}
