import Link from 'next/link';

import type { EngineRun } from '@/lib/types/engine';

/**
 * Who or what started a run, by name: the parent run's workflow (a link to it), the mailbox an email reached, the agent
 * that called the workflow, or the person. The server names it in `startedBy`; until a row carries that, the raw
 * `createdBy` is read for its kind so no run id or prefix reaches the screen.
 */
export function StartedBy({ run, testId }: { run: Pick<EngineRun, 'createdBy' | 'startedBy'>; testId?: string }) {
  const s = run.startedBy;
  if (s?.kind === 'run' && s.runId)
    return (
      <Link href={`/workflows/runs/${encodeURIComponent(s.runId)}`} className="underline-offset-4 hover:underline" title={s.name} data-testid={testId} onClick={(e) => e.stopPropagation()}>
        {s.name}
      </Link>
    );
  if (s) {
    const said = s.kind === 'trigger' ? `Email to ${s.name}` : s.name;
    return (
      <span title={said} data-testid={testId}>
        {said}
      </span>
    );
  }
  const raw = run.createdBy;
  if (raw.startsWith('run:')) {
    const runId = raw.slice(4);
    return (
      <Link href={`/workflows/runs/${encodeURIComponent(runId)}`} className="underline-offset-4 hover:underline" data-testid={testId} onClick={(e) => e.stopPropagation()}>
        Another workflow's run
      </Link>
    );
  }
  if (raw.startsWith('trigger:email:')) return <span data-testid={testId}>Email to {raw.slice('trigger:email:'.length)}</span>;
  const viaAgent = / via agent:\S+$/.exec(raw);
  return <span data-testid={testId}>{viaAgent ? `${raw.slice(0, viaAgent.index)} via an agent` : raw}</span>;
}
