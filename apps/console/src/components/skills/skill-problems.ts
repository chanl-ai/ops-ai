import type { PublishBlocker } from '@/lib/types/references';

/** The key of the skill document's notes block: the stored `instructions`. */
export const NOTES = 'instructions';

/** A line the document writes under a step or under the notes. */
export interface PlacedProblem {
  field: string;
  step?: number;
  message: string;
}

/**
 * Where each problem is written in the skill document. A missing reference is left out: the editor gives it a fix
 * row. A step with several problems reads them as one line, since the editor shows one line per step. A problem that
 * names neither a step nor the notes is the page's to show.
 */
export function placeProblems(problems: readonly PublishBlocker[]): PlacedProblem[] {
  const lines = new Map<string, { field: string; step?: number; messages: string[] }>();
  for (const p of problems) {
    if (p.kind === 'missing_reference' || !p.position) continue;
    const at = p.position.field === 'steps' && p.position.step ? { field: 'steps', step: p.position.step } : p.position.field === NOTES ? { field: NOTES } : null;
    if (!at) continue;
    const key = `${at.field}/${at.step ?? ''}`;
    lines.set(key, { ...at, messages: [...(lines.get(key)?.messages ?? []), p.message] });
  }
  return [...lines.values()].map(({ messages, ...at }) => ({ ...at, message: messages.join(' ') }));
}

const STEP_CODES: readonly string[] = ['bad_step', 'bad_check', 'bad_exit', 'sub_skill_not_held'];

/** A save the service refused because of one step (400 with the step's number), as a problem on that step. */
export function refusedSave(error: unknown): PublishBlocker | null {
  const e = error as { status?: number; code?: string; message?: string; details?: Record<string, unknown> };
  const step = e?.details?.step;
  if (e?.status !== 400 || !e.code || !STEP_CODES.includes(e.code) || typeof step !== 'number') return null;
  return { kind: e.code as PublishBlocker['kind'], id: null, position: { field: 'steps', step, index: null }, message: e.message ?? '' };
}
