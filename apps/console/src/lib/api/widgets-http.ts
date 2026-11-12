import type { ListParams } from '@/lib/types/query';

import type { WidgetsApi } from './widgets-contract';
import { optionsQs } from './options';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;
type Qs = (p: ListParams) => string;

export function createWidgetsHttp(get: Get, send: Send, qs: Qs): WidgetsApi {
  return {
    list: () => get('/widgets'),
    get: (id) => get(`/widgets/${id}`),
    page: (p) => get(`/widgets?${qs(p)}`),
    options: (p, granted) => get(`/widgets/options?${[optionsQs(p), ...granted.map((t) => `granted=${encodeURIComponent(t)}`)].filter(Boolean).join('&')}`),
    create: (input) => send('POST', '/widgets', input),
    update: (id, input) => send('PATCH', `/widgets/${id}`, input),
    requestPublish: (id, version, note) => send('POST', `/widgets/${id}/publish-requests`, { note }),
    retire: (id, reason) => send('POST', `/widgets/${id}/retire`, { reason }),
  };
}
