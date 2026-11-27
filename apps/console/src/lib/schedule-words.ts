import { dateTimeIn } from './format.ts';
import type { ScheduleView } from './types/schedules.ts';

/** What the clock did with the last slot, in the words a panel shows. */
const OUTCOME: Record<NonNullable<ScheduleView['lastOutcome']>, string> = { ran: 'ran', late: 'ran late', skipped: 'skipped', refused: 'refused', missed: 'missed', seen: 'seen' };

/** "Last scheduled run": the slot's time in the schedule's zone, the outcome and its reason, and the run to open. */
export function lastRunWords(s: Pick<ScheduleView, 'lastOutcome' | 'lastSlotAt' | 'lastOutcomeReason' | 'lastRunId'>, tz?: string): { text: string; runHref: string | null } {
  if (!s.lastOutcome || !s.lastSlotAt) return { text: 'Not run yet.', runHref: null };
  const reason = s.lastOutcomeReason ? `: ${s.lastOutcomeReason}` : '';
  return { text: `${dateTimeIn(s.lastSlotAt, tz)} · ${OUTCOME[s.lastOutcome]}${reason}`, runHref: s.lastRunId ? `/build/runs/${encodeURIComponent(s.lastRunId)}` : null };
}
