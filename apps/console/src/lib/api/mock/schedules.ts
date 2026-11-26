import { ApiError } from '../contract';
import type { SchedulesApi } from '../schedules-contract';
import type { EveryRule } from '../../types/schedules';

const ZONES = ['Africa/Nairobi', 'America/Toronto', 'America/New_York', 'Asia/Kolkata', 'Asia/Tokyo', 'Australia/Sydney', 'Europe/London', 'Europe/Paris', 'UTC'];

/** The server's words for an Every rule, as far as the mock needs them; the real ones come from the service. */
function words(rule: EveryRule): string {
  const span = rule.every === 1 ? (rule.unit === 'hours' ? 'hour' : rule.unit === 'minutes' ? 'minute' : 'day') : `${rule.every} ${rule.unit}`;
  const head = rule.every === 1 ? `Every ${span}` : `Every ${span}`;
  return `${head}${rule.start ? ` from ${rule.start}` : ''}, ${rule.tz ?? 'UTC'}`;
}

/** Schedules on the mock: the rules are checked as the service checks the ones a form can get wrong. */
export function createSchedulesMock(): SchedulesApi {
  const refuse = (message: string, field: string) => new ApiError(message, 422, undefined, 'schedule_invalid', { field });
  const check = (rule: unknown): EveryRule => {
    const r = rule as EveryRule;
    if (r.kind !== 'every') return r;
    if (!(r.every >= 1)) throw refuse('Every is a whole number of at least 1.', 'every');
    if (r.unit === 'minutes' && r.every < 5) throw refuse('At least 5 minutes on this install.', 'every');
    if (r.days && r.days.length === 0) throw refuse('Choose at least one weekday.', 'days');
    if (r.between && r.between[1] <= r.between[0]) throw refuse('The hours end before they start.', 'between');
    if (r.tz && !ZONES.includes(r.tz)) throw refuse(`${r.tz} is not a time zone.`, 'tz');
    return r;
  };
  const next = (n: number) => Array.from({ length: n }, (_, i) => new Date(Date.UTC(2026, 10, 24, 10 + i, 0)).toISOString().replace('.000Z', 'Z'));
  return {
    preview: async (rule) => {
      const r = check(rule);
      return { rule: r, words: r.kind === 'every' ? words(r as EveryRule) : r.kind, nextRuns: next(3) };
    },
    zones: async ({ search = '', cursor, limit = 25 }) => {
      const all = ZONES.filter((z) => z.toLowerCase().includes(search.toLowerCase()));
      const from = Number(cursor ?? 0);
      return { data: all.slice(from, from + limit).map((z) => ({ id: z, label: z })), nextCursor: from + limit < all.length ? String(from + limit) : null };
    },
    save: async (workflowId, step, rule) => {
      const r = check(rule);
      return { workflowId, triggerStep: step, rule: r, words: r.kind === 'every' ? words(r as EveryRule) : r.kind, nextRuns: next(3), changedBy: 'usr_mock', changedByName: 'James Richardson', changedAt: new Date().toISOString(), lastSlotAt: null, lastOutcome: null, lastOutcomeReason: null, lastRunId: null, idle: null, idleCode: null };
    },
    clear: async () => undefined,
  };
}
