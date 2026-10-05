import type { ListParams } from '@/lib/types/query';

import type { ToolModulesApi } from './tool-modules-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for tool modules; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createToolModulesHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): ToolModulesApi {
  const base = '/tool-modules';
  return {
    list: (p) => get(`${base}?${qs(p)}`),
    get: (id) => get(`${base}/${id}`),
    catalog: () => get(`${base}/catalog`),
    discover: (source) => send('POST', `${base}/discover`, source),
    create: (i) => send('POST', base, i),
    remove: (id) => send('DELETE', `${base}/${id}`),
    bulkRemove: (ids) => send('POST', `${base}/bulk-delete`, { ids }),
    updateOperation: (id, opId, patch) => send('PATCH', `${base}/${id}/operations/${opId}`, patch),
    publishVersion: (id, note) => send('POST', `${base}/${id}/versions`, { note }),
    discardChanges: (id) => send('DELETE', `${base}/${id}/pending-changes`),
    requestReview: (id, note) => send('POST', `${base}/${id}/reviews`, { note }),
    requestApproval: (id, i) => send('POST', `${base}/${id}/approvals`, i),
    decideApproval: (id, aid, decision, reason) => send('POST', `${base}/${id}/approvals/${aid}/decide`, { decision, reason }),
    revokeApprovals: (id, ids, reason) => send('POST', `${base}/${id}/approvals/revoke`, { ids, reason }),
    setCredentialRef: (id, cid, secretRef) => send('PATCH', `${base}/${id}/credentials/${cid}`, { secretRef }),
    test: (id, i) => send('POST', `${base}/${id}/test`, i),
    activity: (id) => get(`${base}/${id}/activity`),
  };
}
