import type { ChatAttachment, ChatOverridesPatch, ThreadSettings } from '@/lib/types/chat';

/**
 * A chat thread's settings within its agent's limits, and the files a message attaches (c-071). The server refuses
 * an override outside the limits with 422 naming the field (`ApiError.details.field`), and a file of a type or size
 * chat cannot read with 422 saying what it reads.
 */
export interface ChatSettingsApi {
  get(threadId: string): Promise<ThreadSettings>;
  /** Merges into the thread's overrides (null clears a field, a missing one is kept); every later message starts from them. */
  save(threadId: string, patch: ChatOverridesPatch): Promise<ThreadSettings>;
  /** Uploads one file for the next message; its id goes in `SendInput.attachments`. */
  attach(file: File): Promise<ChatAttachment>;
}
