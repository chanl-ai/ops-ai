import type { ChatSettingsApi } from './chat-settings-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for thread settings. */
export function createChatSettingsHttp(get: Get, send: Send): ChatSettingsApi {
  return {
    get: (threadId) => get(`/chat/threads/${threadId}/settings`),
    save: (threadId, patch) => send('PATCH', `/chat/threads/${threadId}/settings`, patch),
  };
}
