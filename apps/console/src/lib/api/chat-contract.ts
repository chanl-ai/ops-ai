import type { BulkResult } from '@/lib/types/domain';
import type {
  ChatAgent,
  ChatFilters,
  ChatStreamEvent,
  ChatThread,
  ChatThreadInput,
  ChatThreadPatch,
  ChatThreadRow,
  ChatWidget,
  MessageFeedback,
  SendInput,
  WidgetAction,
} from '@/lib/types/chat';
import type { ListParams, ListResult } from '@/lib/types/query';

/**
 * Chat with agents inside the platform. Replies run through the same agent version, tool gateway and review
 * gates as a workflow run; widgets are MCP App results the reply carries.
 */
export interface ChatApi {
  /** Live agents the current user may chat with. */
  agents(): Promise<ChatAgent[]>;
  threads: {
    list(params: ListParams<ChatFilters>): Promise<ListResult<ChatThreadRow>>;
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
}
