import type { MemoriesApi } from './memories-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** On the chat base URL (agents-service's root), where memories are served only under /v1. */
export function createMemoriesHttp(get: Get, send: Send): MemoriesApi {
  return {
    list: (agentId) => get(`/v1/me/memories${agentId ? `?agentId=${encodeURIComponent(agentId)}` : ''}`),
    correct: (id, value) => send('PATCH', `/v1/me/memories/${id}`, { value }),
    forget: (id) => send('DELETE', `/v1/me/memories/${id}`),
    forgetAgent: (agentId) => send('DELETE', `/v1/me/memories?agentId=${encodeURIComponent(agentId)}`),
    exportAll: () => get('/v1/me/memories/export'),
  };
}
