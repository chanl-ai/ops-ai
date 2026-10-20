import type { ListParams } from '@/lib/types/query';

import type { ChatApi } from './chat-contract';
import { createChatSettingsHttp } from './chat-settings-http';
import { ApiError } from './contract';
import { createMemoriesHttp } from './memories-http';
import { fetchWithIdentity } from './request-identity';
import { readSse } from './sse';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for chat; replies stream over SSE from POST /chat/threads/:id/messages. */
export function createChatHttp(get: Get, send: Send, qs: (p: ListParams) => string, baseUrl: string): ChatApi {
  return {
    agents: () => get('/chat/agents'),
    defaultAgent: {
      get: () => get('/chat/default-agent'),
      set: (agentId) => send('PUT', '/chat/default-agent', { agentId }),
    },
    settings: createChatSettingsHttp(get, send, baseUrl),
    memories: createMemoriesHttp(get, send),
    threads: {
      list: ({ cursor, ...p }) => get(`/chat/threads?${qs(p)}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
      get: (id) => get(`/chat/threads/${id}`),
      create: (i) => send('POST', '/chat/threads', i),
      update: (id, patch) => send('PATCH', `/chat/threads/${id}`, patch),
      remove: (id) => send('DELETE', `/chat/threads/${id}`),
      bulkUpdate: (ids, patch) => send('POST', '/chat/threads/bulk-update', { ids, patch }),
      bulkRemove: (ids) => send('POST', '/chat/threads/bulk-delete', { ids }),
    },
    async *send(threadId, input, signal) {
      const res = await fetchWithIdentity(`${baseUrl}/chat/threads/${threadId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(input),
        signal,
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new ApiError(body?.error?.message ?? res.statusText, res.status);
      }
      yield* readSse(res);
    },
    feedback: (threadId, messageId, feedback) => send('PUT', `/chat/threads/${threadId}/messages/${messageId}/feedback`, { feedback }),
    widgetAction: (threadId, messageId, widgetId, action) => send('POST', `/chat/threads/${threadId}/messages/${messageId}/widgets/${widgetId}/actions`, action),
    budget: (threadId, answer) => send('POST', `/chat/threads/${threadId}/budget`, answer),
  };
}
