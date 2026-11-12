import type { ListParams } from '@/lib/types/query';

import type { WidgetsApi } from './widgets-contract';
import { optionsQs } from './options';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;
type Qs = (p: ListParams) => string;

export function createWidgetsHttp(get: Get, send: Send, qs: Qs): WidgetsApi {
  return {
    list: () => get('/build/widgets'),
    get: (id) => get(`/build/widgets/${id}`),
    page: (p) => get(`/build/widgets?${qs(p)}`),
    options: (p, granted) => get(`/build/widgets/options?${[optionsQs(p), ...granted.map((t) => `granted=${encodeURIComponent(t)}`)].filter(Boolean).join('&')}`),
    create: (input) => send('POST', '/build/widgets', input),
    update: (id, input) => send('PATCH', `/build/widgets/${id}`, input),
    requestPublish: (id, version, note) => send('POST', `/build/widgets/${id}/publish-requests`, { note }),
    retire: (id, reason) => send('POST', `/build/widgets/${id}/retire`, { reason }),
  };
}
