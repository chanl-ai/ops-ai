import type { ListParams } from '@/lib/types/query';

import type { TemplatesApi } from './templates-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for agent templates; `get`, `send` and `qs` come from the main HTTP client. */
export function createTemplatesHttp(get: Get, send: Send, qs: (p: ListParams) => string): TemplatesApi {
  return {
    list: (p) => get(`/agent-templates?${qs(p)}`),
    get: (id) => get(`/agent-templates/${id}`),
    createAgent: (i) => send('POST', '/agents/from-template', i),
    submit: (i) => send('POST', '/agent-templates/submissions', i),
  };
}
