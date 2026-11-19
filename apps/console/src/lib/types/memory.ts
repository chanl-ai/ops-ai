import type { OpsAI } from '@chanl-ai/ops-ai';

/** What an agent remembers about the person using the console; only ever their own. */
export type MemoryKind = 'fact' | 'preference' | 'episode';

/** A memory as `GET /v1/me/memories` answers it. */
export type Memory = Awaited<ReturnType<OpsAI['raw']['agents']['memory_list_memories']>>[number];

/** One forget, correction, export or retention deletion, as the server stored it. */
export type MemoryAuditRow = Record<string, unknown> & { action: string; actor: string; at: string };

export interface MemoryExport {
  person: string;
  memories: Memory[];
  audit: MemoryAuditRow[];
}
