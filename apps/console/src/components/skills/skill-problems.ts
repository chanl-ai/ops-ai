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

/**
 * A save the service refused because of one step, as a problem on that step. The service answers 400 with the step's
 * number and its own code for what is wrong (a bad check, an ending it does not have, a skill that runs itself); the
 * sentence is what the person reads, so the code is not matched here.
 */
export function refusedSave(error: unknown): PublishBlocker | null {
  const e = error as { status?: number; message?: string; details?: Record<string, unknown> };
  const step = e?.details?.step;
  if (e?.status !== 400 || typeof step !== 'number') return null;
  return { kind: 'bad_step', id: null, position: { field: 'steps', step, index: null }, message: e.message ?? '' };
}

/** Publish blockers the page already says in its own alerts, so the document's list leaves them out. */
const SAID_ELSEWHERE: readonly PublishBlocker['kind'][] = ['deprecated', 'already_published', 'review_open'];

/** The problems a builder fixes in the skill's text. */
export const inText = (problems: readonly PublishBlocker[]): PublishBlocker[] => problems.filter((p) => !SAID_ELSEWHERE.includes(p.kind));
