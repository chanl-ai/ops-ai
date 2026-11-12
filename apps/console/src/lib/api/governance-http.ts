import type { ToolCallFilters } from '@/lib/types/governance';
import type { ListParams } from '@/lib/types/query';

import { ApiError } from './contract';

import type { GovernanceApi } from './governance-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for logs and access; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createGovernanceHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): GovernanceApi {
  return {
    toolCalls: {
      list: (p) => get(`/logs/tool-calls?${qs(p)}`),
      get: (id) => get(`/logs/tool-calls/${id}`),
    },
    audit: {
      list: (p) => get(`/govern/activity/audit?${qs(p)}`),
    },
    access: {
      identities: (p) => get(`/govern/access/identities?${qs(p)}`),
      grants: (p) => get(`/govern/access/grants?${qs(p)}`),
      grant: (i) => send('POST', '/govern/access/grants', i),
      revoke: (ids, reason) => send('POST', '/govern/access/grants/revoke', { ids, reason }),
      extend: (ids, days) => send('POST', '/govern/access/grants/extend', { ids, days }),
      roles: (p) => get(`/govern/access/roles?${qs(p)}`),
      assignRole: (i) => send('POST', '/govern/access/roles', i),
      removeRoles: (ids) => send('POST', '/govern/access/roles/delete', { ids }),
      options: () => get('/govern/access/options'),
    },
  };
}

/**
 * The tool-call log on tools-service's own `GET /v1/executions`: every gateway call, newest first, filtered by the
 * thread it ran for (`runId`), one tool (`tool`) or an app's tool sets (`moduleId`). The route serves rows and pages, not the log's stats or facets, and has no read of one
 * call's payloads yet, so opening a row reports that instead of a sheet.
 */
export function createExecutionsHttp(get: Get): GovernanceApi['toolCalls'] {
  return {
    list: (p: ListParams<ToolCallFilters>) => {
      const q = new URLSearchParams({ page: String(p.page), pageSize: String(p.pageSize) });
      const thread = p.filters?.runId?.[0];
      if (thread) q.set('thread', thread);
      const tool = p.filters?.tool?.[0];
      if (tool) q.set('tool', tool);
      // The route takes one tool set; an app with several sends each, for the route to take them all once it does.
      for (const m of p.filters?.moduleId ?? []) q.append('moduleId', m);
      return get(`/executions?${q}`);
    },
    get: () => Promise.reject(new ApiError('tools-service does not serve one call’s request and response yet.', 501)),
  };
}
