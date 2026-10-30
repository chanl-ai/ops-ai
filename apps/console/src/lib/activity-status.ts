import type { ActivityStatus } from '@/lib/types/activity';

/** Activity's Status column: one of five statuses for every kind of row. */
export const ACTIVITY_STATUS: Record<ActivityStatus, string> = { running: 'Running', waiting: 'Waiting on a person', done: 'Done', failed: 'Failed', skipped: 'Skipped' };

// Outcomes that only restate a status, or a chat's own state, which say nothing beside the status.
const SAYS_NOTHING = new Set(['idle', 'succeeded', 'done', 'started', 'running', 'waiting', 'failed', 'skipped', 'ok']);

/** A row's status as the column shows it, and its own outcome (an End's, an email's) as a note beside the title. */
export function activityStatus(row: { status: ActivityStatus; outcome?: string | null; outcomeText?: string | null }): { label: string; note: string | undefined } {
  const label = ACTIVITY_STATUS[row.status] ?? row.status;
  const said = row.outcomeText ?? row.outcome ?? undefined;
  const quiet = !row.outcome || SAYS_NOTHING.has(row.outcome) || !said || said.toLowerCase() === label.toLowerCase();
  return { label, note: quiet ? undefined : said };
}
