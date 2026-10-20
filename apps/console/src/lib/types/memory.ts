/** What an agent remembers about the person using the console (c-124, c-206); only ever their own. */
export type MemoryKind = 'fact' | 'preference' | 'episode';

export interface Memory {
  id: string;
  agentId: string;
  agentName: string;
  kind: MemoryKind;
  /** A fact's or preference's name (timezone); an episode has none. */
  key: string | null;
  value: string;
  confidence: number;
  /** `extraction` from a chat turn, `person` when they corrected it. */
  source: 'extraction' | 'person';
  sourceThreadId: string | null;
  createdAt: string;
}

/** One forget, correction, export or retention deletion, as the server stored it. */
export type MemoryAuditRow = Record<string, unknown> & { action: string; actor: string; at: string };

export interface MemoryExport {
  person: string;
  memories: Memory[];
  audit: MemoryAuditRow[];
}
