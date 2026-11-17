import type { WorkspacePoliciesApi } from './workspace-policies-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

export function createWorkspacePoliciesHttp(get: Get, send: Send): WorkspacePoliciesApi {
  return {
    list: () => get('/policies'),
    set: (key, value) => send('PUT', `/policies/${encodeURIComponent(key)}`, { value }),
  };
}
