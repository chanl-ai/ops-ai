import type { ListParams } from '@/lib/types/query';

import type { SettingsApi } from './settings-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for team settings; `get`, `send` and `qs` come from the main HTTP client so auth and envelopes match. */
export function createSettingsHttp(get: Get, send: Send, qs: (p: ListParams & { view?: string }) => string): SettingsApi {
  return {
    members: {
      list: (p) => get(`/settings/members?${qs(p)}`),
      invite: (i) => send('POST', '/settings/members/invite', i),
      setRole: (ids, role) => send('POST', '/settings/members/role', { ids, role }),
      remove: (ids) => send('POST', '/settings/members/delete', { ids }),
    },
    notifications: {
      get: () => get('/settings/notifications'),
      update: (i) => send('PUT', '/settings/notifications', i),
    },
    webhooks: {
      list: (p) => get(`/settings/webhooks?${qs(p)}`),
      create: (i) => send('POST', '/settings/webhooks', i),
      setStatus: (id, status) => send('POST', `/settings/webhooks/${id}/status`, { status }),
      remove: (id) => send('DELETE', `/settings/webhooks/${id}`),
      deliveries: (id, p) => get(`/settings/webhooks/${id}/deliveries?${qs(p)}`),
      resend: (id, deliveryId) => send('POST', `/settings/webhooks/${id}/deliveries/${deliveryId}/resend`),
    },
    apiKeys: {
      list: (p) => get(`/settings/api-keys?${qs(p)}`),
      create: (i) => send('POST', '/settings/api-keys', i),
      revoke: (id) => send('DELETE', `/settings/api-keys/${id}`),
    },
    usage: { get: (days) => get(`/settings/usage?days=${days}`) },
    lookups: () => get('/settings/lookups'),
  };
}
