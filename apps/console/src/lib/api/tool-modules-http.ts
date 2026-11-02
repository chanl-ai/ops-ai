import type { ListParams } from '@/lib/types/query';

import type { ToolModuleDetail } from '@/lib/types/tool-modules';

import { type HeldHost, unlessHeld } from './held-host';
import type { ToolModulesApi } from './tool-modules-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for tool modules; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createToolModulesHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): ToolModulesApi {
  const base = '/tool-modules';
  return {
    grants: ({ view, search, page, pageSize }) => get(`${base}/grants?${new URLSearchParams({ view, page: String(page), pageSize: String(pageSize), ...(search ? { search } : {}) })}`),
    list: (p) => get(`${base}?${qs(p)}`),
    get: (id) => get(`${base}/${id}`),
    discover: (source) => send('POST', `${base}/discover`, source),
    // The three writes that may first set an app's address can be held for Security (202) instead of saved.
    create: (i) => send<ToolModuleDetail | HeldHost>('POST', base, i).then(unlessHeld),
    createBlankModule: (i) => send<ToolModuleDetail | HeldHost>('POST', `${base}/blank`, i).then(unlessHeld),
    updateModuleDetails: (id, patch) => send('PATCH', `${base}/${id}`, patch),
    addOperation: (id, i) => send<ToolModuleDetail | HeldHost>('POST', `${base}/${id}/operations`, i).then(unlessHeld),
    importOperations: (id, i) => send('POST', `${base}/${id}/operations/import`, i),
    setConnection: (id, connectionId) => send('PUT', `${base}/${id}/connection`, { connectionId }),
    remove: (id) => send('DELETE', `${base}/${id}`),
    bulkRemove: (ids) => send('POST', `${base}/bulk-delete`, { ids }),
    updateOperation: (id, opId, patch) => send('PATCH', `${base}/${id}/operations/${opId}`, patch),
    publishVersion: (id, note) => send('POST', `${base}/${id}/versions`, { note }),
    discardChanges: (id) => send('DELETE', `${base}/${id}/pending-changes`),
    requestReview: (id, note) => send('POST', `${base}/${id}/reviews`, { note }),
    requestApproval: (id, i) => send('POST', `${base}/${id}/approvals`, i),
    decideApproval: (id, aid, decision, reason) => send('POST', `${base}/${id}/approvals/${aid}/decide`, { decision, reason }),
    revokeApprovals: (id, ids, reason) => send('POST', `${base}/${id}/approvals/revoke`, { ids, reason }),
    test: (id, i) => send('POST', `${base}/${id}/test`, i),
    activity: (id) => get(`${base}/${id}/activity`),
  };
}
