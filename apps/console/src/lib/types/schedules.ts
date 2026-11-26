/** The rule kinds the schedule form edits; a rule of any other kind is shown in words and left as it is. */
export interface EveryRule {
  kind: 'every';
  every: number;
  unit: 'minutes' | 'hours' | 'days';
  /** HH:MM; the time of day the first run of a day is counted from. */
  start?: string;
  /** Weekdays, `mon` to `sun`; left out for every day. */
  days?: string[];
  /** HH:MM twice: runs only between them. */
  between?: [string, string];
  tz?: string;
}

export type ScheduleRule = EveryRule | { kind: string; [field: string]: unknown };

/** Why a saved schedule starts nothing; the panel picks its alert by this, never by the sentence. */
export type IdleCode = 'no_live_version' | 'paused' | 'step_missing' | 'not_schedulable';

/** The schedule on one trigger step, as the server words it (GET .../triggers/{step}/schedule, `schedules[]` of a workflow). */
export interface ScheduleView {
  workflowId: string;
  triggerStep: string;
  rule: ScheduleRule;
  words: string;
  nextRuns: string[];
  changedBy: string;
  changedByName: string;
  changedAt: string;
  lastSlotAt: string | null;
  lastOutcome: 'ran' | 'late' | 'skipped' | 'refused' | 'missed' | 'seen' | null;
  lastOutcomeReason: string | null;
  lastRunId: string | null;
  idle: string | null;
  idleCode: IdleCode | null;
}

/** POST /v1/schedules/preview: the rule as it would be saved, in words, with its next three runs. */
export interface SchedulePreview {
  rule: ScheduleRule;
  words: string;
  nextRuns: string[];
}
