import type { ListParams } from '@/lib/types/query';

import type { ModelRiskApi } from './model-risk-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for the model risk inventory; `get`, `send` and `qs` come from the main HTTP client. */
export function createModelRiskHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): ModelRiskApi {
  return {
    list: (p) => get(`/govern/models?${qs(p)}`),
    get: (id) => get(`/govern/models/${id}`),
    requestValidation: (ids, note) => send('POST', '/govern/models/request-validation', { ids, note }),
    setNextReview: (ids, date) => send('POST', '/govern/models/next-review', { ids, date }),
    changeTier: (id, i) => send('POST', `/govern/models/${id}/tier`, i),
    addCondition: (id, i) => send('POST', `/govern/models/${id}/conditions`, i),
    setConditionStatus: (id, cid, status, reason) => send('PATCH', `/govern/models/${id}/conditions/${cid}`, { status, reason }),
    options: () => get('/govern/models/options'),
  };
}
