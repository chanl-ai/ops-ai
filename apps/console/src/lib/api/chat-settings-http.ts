import type { ChatSettingsApi } from './chat-settings-contract';

type Get = <T>(path: string) => Promise<T>;
type Send = <T>(method: string, path: string, body?: unknown) => Promise<T>;

/** REST routes for thread settings. */
export function createChatSettingsHttp(get: Get, send: Send): ChatSettingsApi {
  return {
    get: (threadId) => get(`/chat/threads/${threadId}/settings`),
    save: (threadId, patch) => send('PATCH', `/chat/threads/${threadId}/settings`, patch),
    newChatConnectors: (agentId) => get(agentId ? `/chat/connectors?agentId=${encodeURIComponent(agentId)}` : '/chat/connectors'),
    connectors: (threadId) => get(`/chat/threads/${threadId}/connectors`),
    setConnectors: (threadId, off) => send('PUT', `/chat/threads/${threadId}/connectors`, { off }),
  };
}
