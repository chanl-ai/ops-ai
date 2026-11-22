import type { ListParams, ListResult } from '@/lib/types/query';

import type { DiscoveredOperation, DiscoveryResult, ModuleSource, ToolModuleDetail } from '@/lib/types/tool-modules';

import { type HeldHost, unlessHeld } from './held-host';
import type { ToolModulesApi } from './tool-modules-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

interface StoredDiscovery extends Omit<DiscoveryResult, 'operations'> {
  id: string;
  operationTotal: number;
}

/**
 * The discovery with every operation, read from the stored discovery a page at a time. Bridges the picker, which
 * searches in the browser, until it reads one page at a time through the shared server list.
 */
async function discoverAll(get: Get, send: Send, source: ModuleSource): Promise<DiscoveryResult> {
  const found = await send<StoredDiscovery>('POST', '/tool-modules/discover', source);
  const operations: DiscoveredOperation[] = [];
  for (let page = 1; ; page++) {
    const listed = await get<ListResult<DiscoveredOperation>>(`/tool-modules/discoveries/${found.id}/operations?page=${page}&pageSize=50`);
    operations.push(...listed.data.map(({ added: _added, ...o }: DiscoveredOperation & { added?: boolean }) => o));
    if (!listed.pagination.hasNext) return { ...found, operations };
  }
}

/** REST routes for tool modules; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createToolModulesHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): ToolModulesApi {
  const base = '/tool-modules';
  return {
    grants: ({ view, search, page, pageSize }) => get(`${base}/grants?${new URLSearchParams({ view, page: String(page), pageSize: String(pageSize), ...(search ? { search } : {}) })}`),
    list: (p) => get(`${base}?${qs(p)}`),
    get: (id) => get(`${base}/${id}`),
    discover: (source) => discoverAll(get, send, source),
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
