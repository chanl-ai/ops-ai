import type { ListParams } from '@/lib/types/query';

import type { GuardrailsApi } from './guardrails-contract';
import { optionsQs } from './options';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;
type Qs = (p: ListParams) => string;

export function createGuardrailsHttp(get: Get, send: Send, qs: Qs): GuardrailsApi {
  return {
    list: () => get('/guardrails'),
    page: (p) => get(`/guardrails?${qs(p)}`),
    options: (p) => get(`/guardrails/options?${optionsQs(p)}`),
    get: (id) => get(`/guardrails/${id}`),
    create: (i) => send('POST', '/guardrails', { ...i, kind: 'blocked_topics' }),
    update: (id, patch) => send('PATCH', `/guardrails/${id}`, patch),
    requestPublish: (id, version, note) => send('POST', `/guardrails/${id}/publish-requests`, { version, note }),
    setStatus: (id, status) => send('POST', `/guardrails/${id}/status`, { status }),
    remove: (id) => send('DELETE', `/guardrails/${id}`),
  };
}
