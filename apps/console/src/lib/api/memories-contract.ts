import type { Memory, MemoryExport } from '@/lib/types/memory';

/** The caller's own memories with each agent (`/v1/me/memories`); no route reads another person's. */
export interface MemoriesApi {
  /** Newest first; `agentId` keeps one agent's. */
  list(agentId?: string): Promise<Memory[]>;
  /** Replaces the value; the old one is kept as superseded and no longer loaded into chats. */
  correct(id: string, value: string): Promise<Memory>;
  /** Forgets one memory and its earlier versions at once. */
  forget(id: string): Promise<void>;
  /** Forgets everything one agent keeps about the caller; the number forgotten. */
  forgetAgent(agentId: string): Promise<{ forgotten: number }>;
  exportAll(): Promise<MemoryExport>;
}
