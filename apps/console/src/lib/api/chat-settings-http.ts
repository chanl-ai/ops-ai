import type { ChatAttachment } from '@/lib/types/chat';

import type { ChatSettingsApi } from './chat-settings-contract';
import { ApiError } from './contract';
import { fetchWithIdentity } from './request-identity';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for thread settings, and the attachment upload, whose body is the file's bytes. */
export function createChatSettingsHttp(get: Get, send: Send, baseUrl: string): ChatSettingsApi {
  return {
    get: (threadId) => get(`/chat/threads/${threadId}/settings`),
    save: (threadId, patch) => send('PATCH', `/chat/threads/${threadId}/settings`, patch),
    async attach(file) {
      const res = await fetchWithIdentity(`${baseUrl}/chat/attachments?name=${encodeURIComponent(file.name)}`, {
        method: 'POST',
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
        body: file,
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) throw new ApiError(body?.error?.message ?? res.statusText, res.status, undefined, body?.error?.code, body?.error?.details);
      return body.data as ChatAttachment;
    },
  };
}
