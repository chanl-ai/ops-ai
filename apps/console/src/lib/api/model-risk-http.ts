import type { ListParams } from '@/lib/types/query';

import type { ModelRiskApi } from './model-risk-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for the model risk inventory; `get`, `send` and `qs` come from the main HTTP client. */
export function createModelRiskHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): ModelRiskApi {
  return {
    list: (p) => get(`/model-risk?${qs(p)}`),
    get: (id) => get(`/model-risk/${id}`),
    requestValidation: (ids, note) => send('POST', '/model-risk/request-validation', { ids, note }),
    setNextReview: (ids, date) => send('POST', '/model-risk/next-review', { ids, date }),
    changeTier: (id, i) => send('POST', `/model-risk/${id}/tier`, i),
    addCondition: (id, i) => send('POST', `/model-risk/${id}/conditions`, i),
    setConditionStatus: (id, cid, status, reason) => send('PATCH', `/model-risk/${id}/conditions/${cid}`, { status, reason }),
    options: () => get('/model-risk/options'),
  };
}
