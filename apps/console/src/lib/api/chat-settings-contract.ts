import type { ChatOverridesPatch, ThreadSettings } from '@/lib/types/chat';

/**
 * A chat thread's settings within its agent's limits. The server refuses an override outside the limits with 422
 * naming the field (`ApiError.details.field`). A message's files are uploaded through Files (`chat_attachment`).
 */
export interface ChatSettingsApi {
  get(threadId: string): Promise<ThreadSettings>;
  /** Merges into the thread's overrides (null clears a field, a missing one is kept); every later message starts from them. */
  save(threadId: string, patch: ChatOverridesPatch): Promise<ThreadSettings>;
}
