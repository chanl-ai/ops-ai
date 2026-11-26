import type { ListParams } from '@/lib/types/query';

import type { ModelAliasesApi } from './model-aliases-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** models-service's `/models/aliases` routes. */
export function createModelAliasesHttp(get: Get, send: Send, qs: (p: ListParams) => string): ModelAliasesApi {
  return {
    list: (p) => get(`/models/aliases?${qs(p)}`),
    create: (input) => send('POST', '/models/aliases', input),
    newVersion: (name, input) => send('POST', `/models/aliases/${encodeURIComponent(name)}/versions`, input),
  };
}
