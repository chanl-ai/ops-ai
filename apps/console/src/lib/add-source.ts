import type { IngestStrategy } from './types/knowledge-ingest';
import type { Schedule, SourceInput, SourceKindOption } from './types/knowledge';

/** The two steps that call a model at each sync: likely questions (`faq`) and FAQ drafts (`faq_pairs`). */
export interface AiSwitches {
  questions: boolean;
  drafts: boolean;
}

/** The kind's default steps with the two AI steps set as switched; the rest of the kind's steps are kept as they are. */
export function strategiesWith(defaults: IngestStrategy[], ai: AiSwitches): IngestStrategy[] {
  const kept = defaults.filter((s) => s !== 'faq' && s !== 'faq_pairs');
  return [...kept, ...(ai.questions ? (['faq'] as const) : []), ...(ai.drafts ? (['faq_pairs'] as const) : [])];
}

/** Whether the kind's defaults already turn an AI step on, so the switch starts on. */
export const aiDefaults = (kind: SourceKindOption): AiSwitches => ({
  questions: kind.defaults.ingest.strategies.includes('faq'),
  drafts: kind.defaults.ingest.strategies.includes('faq_pairs'),
});

/**
 * Pieces a page or file is split into before the source exists: one for a short page, five for a long one. kb-service
 * makes one model call per piece for each AI step, so the range of calls follows from these two bounds.
 */
export const PIECES_LOW = 1;
export const PIECES_HIGH = 5;

/** The first sync's model calls for `units` pages or files, as a low-to-high range; null when no AI step is on. */
export function firstSyncCalls(units: number, ai: AiSwitches): { low: number; high: number } | null {
  const steps = Number(ai.questions) + Number(ai.drafts);
  if (!steps || units <= 0) return null;
  return { low: units * PIECES_LOW * steps, high: units * PIECES_HIGH * steps };
}

/** What Add source sends to `POST /v1/sources` (the caller adds `kbIds` and `sync`): the kind, its values, schedule and steps. */
export function createInput(p: { kind: SourceKindOption; name: string; values: Record<string, unknown>; schedule: Schedule; ai: AiSwitches; fileIds: string[] }): SourceInput {
  const tool = p.kind.type === 'tool';
  return {
    type: p.kind.type,
    name: p.name.trim(),
    config: tool ? { plugin: p.kind.plugin, source: p.kind.source, values: p.values } : {},
    schedule: p.schedule,
    ingest: { strategies: strategiesWith(p.kind.defaults.ingest.strategies, p.ai) },
    ...(tool ? {} : { fileIds: p.fileIds }),
  };
}
