import type { ChatStreamEvent } from '@/lib/types/chat';
import type { ListParams } from '@/lib/types/query';

import type { ChatApi } from './chat-contract';
import { ApiError } from './contract';
import { currentTeamId } from './team-context';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** Reads a server-sent event stream where each `data:` line is one JSON ChatStreamEvent. */
async function* readSse(res: Response): AsyncIterable<ChatStreamEvent> {
  if (!res.body) return;
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    const frames = buf.split('\n\n');
    buf = frames.pop() ?? '';
    for (const f of frames) {
      const data = f
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trim())
        .join('');
      if (data) yield JSON.parse(data) as ChatStreamEvent;
    }
  }
}

/** REST routes for chat; replies stream over SSE from POST /chat/threads/:id/messages. */
export function createChatHttp(get: Get, send: Send, qs: (p: ListParams) => string, baseUrl: string): ChatApi {
  return {
    agents: () => get('/chat/agents'),
    threads: {
      list: (p) => get(`/chat/threads?${qs(p)}`),
      get: (id) => get(`/chat/threads/${id}`),
      create: (i) => send('POST', '/chat/threads', i),
      update: (id, patch) => send('PATCH', `/chat/threads/${id}`, patch),
      remove: (id) => send('DELETE', `/chat/threads/${id}`),
      bulkUpdate: (ids, patch) => send('POST', '/chat/threads/bulk-update', { ids, patch }),
      bulkRemove: (ids) => send('POST', '/chat/threads/bulk-delete', { ids }),
    },
    async *send(threadId, input, signal) {
      const res = await fetch(`${baseUrl}/chat/threads/${threadId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', 'X-Team-Id': currentTeamId() },
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
  };
}
