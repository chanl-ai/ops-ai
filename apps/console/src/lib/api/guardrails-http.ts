import type { ListParams } from '@/lib/types/query';

import type { GuardrailsApi } from './guardrails-contract';
import { optionsQs } from './options';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;
type Qs = (p: ListParams) => string;

export function createGuardrailsHttp(get: Get, send: Send, qs: Qs): GuardrailsApi {
  return {
    list: () => get('/build/guardrails'),
    page: (p) => get(`/build/guardrails?${qs(p)}`),
    options: (p) => get(`/build/guardrails/options?${optionsQs(p)}`),
    get: (id) => get(`/build/guardrails/${id}`),
    create: (i) => send('POST', '/build/guardrails', { ...i, kind: 'blocked_topics' }),
    update: (id, patch) => send('PATCH', `/build/guardrails/${id}`, patch),
    requestPublish: (id, version, note) => send('POST', `/build/guardrails/${id}/publish-requests`, { version, note }),
    setStatus: (id, status) => send('POST', `/build/guardrails/${id}/status`, { status }),
    remove: (id) => send('DELETE', `/build/guardrails/${id}`),
  };
}
