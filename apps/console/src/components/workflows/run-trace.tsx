'use client';

import Link from 'next/link';
import { AlertCircle, Bot, CheckCircle2, CircleDashed, Flag, Loader2, UserCheck, Wrench, Zap } from 'lucide-react';

import type { RunStatus, RunStep, WorkflowRun } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

const pill = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap';

const STATUS: Record<RunStatus, { label: string; cls: string }> = {
  completed: { label: 'Completed', cls: 'border-success/40 bg-success/10 text-success-text' },
  waiting_review: { label: 'Waiting on review', cls: 'border-warning/40 bg-warning/10 text-warning-text' },
  failed: { label: 'Failed', cls: 'border-destructive/40 bg-destructive/10 text-destructive' },
  running: { label: 'Running', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300' },
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <span className={cn(pill, STATUS[status].cls)}>{STATUS[status].label}</span>;
}

export const RUN_STATUS_OPTIONS = (Object.keys(STATUS) as RunStatus[]).map((value) => ({ value, label: STATUS[value].label }));

const KIND_ICON: Record<RunStep['kind'], typeof Bot> = { trigger: Zap, agent: Bot, tool: Wrench, review: UserCheck, action: Flag, end: Flag };

export const duration = (ms: number) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);

/** Step-by-step log of one run, top to bottom, with the step that stopped it called out. */
export function RunTrace({ run }: { run: WorkflowRun }) {
  return (
    <div className="flex flex-col gap-5">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border text-sm sm:grid-cols-4">
        {[
          ['Status', <RunStatusBadge key="s" status={run.status} />],
          ['Version', `v${run.version}`],
          ['Duration', duration(run.durationMs)],
          ['Steps', String(run.steps.length)],
        ].map(([k, v]) => (
          <div key={k as string} className="bg-card p-3">
            <dt className="text-xs text-muted-foreground">{k}</dt>
            <dd className="mt-0.5 font-medium tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>

      {run.trigger && (
        <p className="text-sm text-muted-foreground" data-testid="run-trigger">
          {run.trigger}
        </p>
      )}
      {run.error && (
        <p className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" /> {run.error}
        </p>
      )}
      {run.reviewId && (
        <p className="flex items-center justify-between gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning-text">
          This run is paused at a review gate.
          <Link href={`/reviews?review=${run.reviewId}`} className="font-medium underline underline-offset-2">
            Open {run.reviewId}
          </Link>
        </p>
      )}

      <ol className="relative flex flex-col" data-testid="run-trace">
        {run.steps.map((s, i) => {
          const Icon = KIND_ICON[s.kind];
          const StatusIcon = s.status === 'done' ? CheckCircle2 : s.status === 'failed' ? AlertCircle : s.status === 'waiting' ? Loader2 : CircleDashed;
          return (
            <li key={`${s.nodeId}-${i}`} className="relative flex gap-3 pb-4 last:pb-0">
              {i < run.steps.length - 1 && <span className="absolute top-7 bottom-0 left-[13px] w-px bg-border" aria-hidden />}
              <div className={cn('z-10 flex size-7 shrink-0 items-center justify-center rounded-full border bg-card', s.status === 'failed' && 'border-destructive/50', s.status === 'waiting' && 'border-warning/60')}>
                <Icon className="size-3.5 text-muted-foreground" />
              </div>
              <div className={cn('min-w-0 flex-1 rounded-lg border px-3 py-2', s.status === 'skipped' && 'opacity-50')}>
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{s.label}</span>
                  <StatusIcon
                    className={cn(
                      'size-3.5 shrink-0',
                      s.status === 'done' && 'text-success-text',
                      s.status === 'failed' && 'text-destructive',
                      s.status === 'waiting' && 'animate-spin text-warning-text',
                      s.status === 'skipped' && 'text-muted-foreground',
                    )}
                    aria-label={s.status}
                  />
                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">{s.status === 'skipped' ? 'skipped' : duration(s.durationMs)}</span>
                </div>
                {s.detail && <p className={cn('mt-0.5 text-xs', s.status === 'failed' ? 'text-destructive' : 'text-muted-foreground')}>{s.detail}</p>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
