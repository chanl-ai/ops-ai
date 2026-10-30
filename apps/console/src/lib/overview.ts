import { relativeTime } from './format.ts';
import type { Overview, OverviewCase, OverviewRun, OverviewTask } from './types/domain.ts';

/** What the shell reads from GET /v1/overview, with every list and count present. */
export interface OverviewLists {
  counts: { waitingForMe: number; runsInFlight: number; casesDue: number };
  waitingForMe: OverviewTask[];
  runsInFlight: OverviewRun[];
  casesDue: OverviewCase[];
}

/**
 * The overview's lists with a missing field read as empty: the sidebar, Chat and Overview are on every page, so an
 * agents-service still serving an older overview (no `counts`, no lists) must leave them empty, never crash the page (c-552).
 */
export function readOverview(o: Partial<Overview> | undefined): OverviewLists {
  return {
    counts: { waitingForMe: o?.counts?.waitingForMe ?? 0, runsInFlight: o?.counts?.runsInFlight ?? 0, casesDue: o?.counts?.casesDue ?? 0 },
    waitingForMe: o?.waitingForMe ?? [],
    runsInFlight: o?.runsInFlight ?? [],
    casesDue: o?.casesDue ?? [],
  };
}

export interface Hint {
  id: 'task' | 'case' | 'run';
  label: string;
  detail: string;
  text: string;
}

/** Up to three hints from the person's own work (c-552): the Human Task waiting longest, the case due soonest, the newest
 * run in flight, each read from the overview's first row of that kind. A clicked hint sends its text as the first message. */
export function hintsFrom(raw: Partial<Overview> | undefined, now: number = Date.now()): Hint[] {
  const o = readOverview(raw);
  const task = o.waitingForMe[0];
  const due = o.casesDue[0];
  const run = o.runsInFlight[0];
  const out: Hint[] = [];
  if (task) out.push({ id: 'task', label: task.title, detail: `Human Task waiting for you since ${relativeTime(task.createdAt, now)}`, text: `What do I need to decide on ${task.title}?` });
  if (due) out.push({ id: 'case', label: due.subject, detail: due.resolutionDueAt && new Date(due.resolutionDueAt).getTime() < now ? 'Case past its deadline' : 'Case due today', text: `Where is the case ${due.subject} up to?` });
  if (run) out.push({ id: 'run', label: run.subject, detail: run.state === 'waiting' ? 'Run waiting on a person' : 'Run in progress', text: `What is happening with the ${run.subject} run?` });
  return out;
}
