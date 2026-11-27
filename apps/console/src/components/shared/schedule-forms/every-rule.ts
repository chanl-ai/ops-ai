import type { EveryRule } from '@/lib/types/schedules';

export const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const;
export const DAY_NAMES: Record<(typeof DAYS)[number], string> = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' };

/** The Every form's fields as typed: text for the numbers and times, so what a person typed is never rewritten. */
export interface EveryFormValue {
  every: string;
  unit: EveryRule['unit'];
  start: string;
  days: string[];
  from: string;
  to: string;
  tz: string;
}

/** The form's fields for a saved rule, or the defaults (every hour, every day, no window) for none. */
export function formOf(rule: EveryRule | undefined, tz = 'UTC'): EveryFormValue {
  return {
    every: String(rule?.every ?? 1),
    unit: rule?.unit ?? 'hours',
    start: rule?.start ?? '',
    days: rule?.days?.length ? [...rule.days] : [...DAYS],
    from: rule?.between?.[0] ?? '',
    to: rule?.between?.[1] ?? '',
    tz: rule?.tz ?? tz,
  };
}

/** The rule the form means: every day is no `days`, and a window needs both of its times. */
export function ruleOf(form: EveryFormValue): EveryRule {
  const rule: EveryRule = { kind: 'every', every: Number(form.every), unit: form.unit };
  if (form.start) rule.start = form.start;
  if (form.days.length < DAYS.length) rule.days = DAYS.filter((d) => form.days.includes(d));
  if (form.from && form.to) rule.between = [form.from, form.to];
  if (form.tz) rule.tz = form.tz;
  return rule;
}
