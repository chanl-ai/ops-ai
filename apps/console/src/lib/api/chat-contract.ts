import type { BulkResult } from '@/lib/types/domain';
import type {
  BudgetAnswer,
  ChatAgent,
  ChatStreamEvent,
  ChatThread,
  ChatThreadInput,
  ChatThreadList,
  ChatThreadListParams,
  ChatThreadPatch,
  ChatWidget,
  MessageFeedback,
  SendInput,
  TeamDefaultAgent,
  WidgetAction,
} from '@/lib/types/chat';

import type { ChatSettingsApi } from './chat-settings-contract';
import type { MemoriesApi } from './memories-contract';

/**
 * Chat with agents inside the platform. Replies run through the same agent version, tool gateway and review
 * gates as a workflow run; widgets are MCP App results the reply carries.
 */
export interface ChatApi {
  /** Live agents the current user may chat with. */
  agents(): Promise<ChatAgent[]>;
  /** The agent the team's new chats start on (c-174); `set` is a team admin's (403 otherwise). */
  defaultAgent: {
    get(): Promise<TeamDefaultAgent>;
    set(agentId: string): Promise<TeamDefaultAgent>;
  };
  /** A thread's settings within its agent's limits, and message attachments (c-071). */
  settings: ChatSettingsApi;
  /** What agents remember about the caller, which they correct, forget and export (c-206). */
  memories: MemoriesApi;
  threads: {
    list(params: ChatThreadListParams): Promise<ChatThreadList>;
    get(id: string): Promise<ChatThread>;
    create(input: ChatThreadInput): Promise<ChatThread>;
    update(id: string, patch: ChatThreadPatch): Promise<ChatThread>;
    remove(id: string): Promise<void>;
    bulkUpdate(ids: string[], patch: Pick<ChatThreadPatch, 'pinned' | 'archived'>): Promise<BulkResult>;
    bulkRemove(ids: string[]): Promise<BulkResult>;
  };
  /**
   * Sends a message and streams the reply. The server stores both messages; aborting the signal keeps the
   * text so far as a stopped reply.
   */
  send(threadId: string, input: SendInput, signal?: AbortSignal): AsyncIterable<ChatStreamEvent>;
  feedback(threadId: string, messageId: string, feedback: MessageFeedback | null): Promise<void>;
  /** Approve, reject or submit a widget. Approvals decide the linked review through the review flow. */
  widgetAction(threadId: string, messageId: string, widgetId: string, action: WidgetAction): Promise<ChatWidget>;
  /** Answers a spent conversation budget; the paused turn runs and the conversation comes back with its reply.
   * 403 for anyone but the owner (continue) or a team admin (raise). */
  budget(threadId: string, answer: BudgetAnswer): Promise<ChatThread>;
}
