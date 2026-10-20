import type { WidgetDeploymentsApi } from './widget-deployments-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** `baseUrl` is the transport's base (the agents service's `/v1`); the script sits beside `/v1` on the same host. */
export function createWidgetDeploymentsHttp(get: Get, send: Send, baseUrl: string): WidgetDeploymentsApi {
  return {
    list: (agentId) => get(`/widget-deployments?agentId=${encodeURIComponent(agentId)}`),
    create: (input) => send('POST', '/widget-deployments', input),
    update: (id, patch) => {
      const { retired, ...change } = patch;
      return retired ? send('POST', `/channels/${encodeURIComponent(id)}/retire`) : send('PATCH', `/channels/${encodeURIComponent(id)}`, change);
    },
    keys: (id) => get(`/widget-deployments/${id}/keys`),
    createKey: (id, name, expiresInDays) => send('POST', `/widget-deployments/${id}/keys`, { name, ...(expiresInDays ? { expiresInDays } : {}) }),
    revokeKey: (id, keyId) => send('POST', `/widget-deployments/${id}/keys/${keyId}/revoke`),
    previewSession: (id) => send('POST', `/widget-deployments/${id}/preview-session`),
    scriptUrl: () => `${baseUrl.replace(/\/v1\/?$/, '')}/embed/v1.js`,
  };
}
