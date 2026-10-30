import type { BatchesApi } from './batches-contract';
import { ApiError } from './contract';
import { fetchWithIdentity } from './request-identity';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** agents-service's batch routes (routers/batches.py) under `baseUrl`. */
export function createBatchesHttp(get: Get, send: Send, baseUrl: string): BatchesApi {
  const at = (s: string) => encodeURIComponent(s);
  return {
    dryRun: (workflowId, input) => send('POST', `/workflows/${at(workflowId)}/batches`, { ...input, dryRun: true }),
    start: (workflowId, input) => send('POST', `/workflows/${at(workflowId)}/batches`, { ...input, dryRun: false }),
    get: (batchId) => get(`/batches/${at(batchId)}`),
    retryFailed: (batchId) => send('POST', `/batches/${at(batchId)}/retry`),
    // The route needs the person's token, which a plain link cannot carry, so the bytes are fetched with it and
    // handed to the page as a blob link, as Files' downloads are on the local backend.
    resultsCsv: async (batchId) => {
      const res = await fetchWithIdentity(`${baseUrl}/batches/${at(batchId)}/results.csv`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new ApiError(body?.error?.message ?? `The download was refused (${res.status}).`, res.status, body?.error?.team, body?.error?.code);
      }
      return { url: URL.createObjectURL(await res.blob()), name: `results-${batchId}.csv` };
    },
  };
}
