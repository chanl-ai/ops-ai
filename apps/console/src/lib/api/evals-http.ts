import type { ListParams } from '@/lib/types/query';

import type { EvalsApi } from './evals-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for agent evals; `get`, `send` and `qs` come from the main HTTP client. */
export function createEvalsHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): EvalsApi {
  return {
    suites: (aid) => get(`/agents/${aid}/eval-suites`),
    cases: (aid, p) => get(`/agents/${aid}/eval-cases?${qs(p)}`),
    createCase: (aid, i) => send('POST', `/agents/${aid}/eval-cases`, i),
    importCases: (aid, rows, fileId) => send('POST', `/agents/${aid}/eval-cases/import`, { rows, fileId }),
    caseFromTurn: (aid, i) => send('POST', `/agents/${aid}/eval-cases/from-turn`, i),
    removeCase: (id) => send('DELETE', `/eval-cases/${id}`),
    bulkRemoveCases: (ids) => send('POST', '/eval-cases/bulk-delete', { ids }),
    run: (aid) => send('POST', `/agents/${aid}/eval-runs`),
    runs: (aid, p) => get(`/agents/${aid}/eval-runs?${qs(p)}`),
    getRun: (id) => get(`/eval-runs/${id}`),
    latest: (aid) => get(`/agents/${aid}/eval-runs/latest`),
    options: (aid) => get(`/agents/${aid}/eval-cases/options`),
  };
}
