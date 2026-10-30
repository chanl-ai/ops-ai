import type { EngineRun } from '@/lib/types/engine';
import type { ListResult } from '@/lib/types/query';

import type { EngineApi } from './engine-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** The runner's routes on agents-service; `get` and `send` come from a client whose base URL ends in /v1. */
export function createEngineHttp(get: Get, send: Send): EngineApi {
  return {
    nodeTypes: () => get('/workflows/node-types'),
    definition: (id, version) => get(`/workflows/definitions/${encodeURIComponent(id)}${version ? `?version=${version}` : ''}`),
    validate: (definition) => send('POST', '/workflows/definitions/validate', { definition }),
    publish: (definition) => send('POST', '/workflows/definitions', { definition }),
    deleteDefinition: (id) => send('DELETE', `/workflows/definitions/${encodeURIComponent(id)}`),
    requestPublish: (id, input) => send('POST', `/workflows/definitions/${encodeURIComponent(id)}/publish-requests`, input),
    setPaused: (id, paused) => send('POST', `/workflows/definitions/${encodeURIComponent(id)}/${paused ? 'pause' : 'resume'}`),
    options: (source) => get(`/workflows/option-sources?source=${source}`),
    startRun: (input) => send('POST', '/runs', input),
    startWorkflow: (input) => send('POST', '/runs/start', input),
    runs: async ({ workflowId, status = [], page = 1, pageSize = 25 }) => {
      const qs = new URLSearchParams({ page: String(page), pageSize: String(pageSize), ...(workflowId ? { workflowId } : {}) });
      for (const s of status) qs.append('status', s);
      return get<ListResult<EngineRun>>(`/runs?${qs}`);
    },
    run: (runId) => get(`/runs/${encodeURIComponent(runId)}`),
    cancelRun: (runId) => send('POST', `/runs/${encodeURIComponent(runId)}/cancel`),
    retryRun: (runId) => send('POST', `/runs/${encodeURIComponent(runId)}/retry`),
    runSetAsideEmail: (eventId) => send('POST', `/runs/set-aside-emails/${encodeURIComponent(eventId)}/run`),
  };
}
