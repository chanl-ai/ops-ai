'use client';

import type { ColumnDef } from '@tanstack/react-table';
import { HeartPulse, ShieldCheck } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Note } from '@/components/shared/setting/note';
import { Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { useBackground } from '@/hooks/activity-queries';
import { ApiError } from '@/lib/api';
import { dateTime, plural, relativeTime } from '@/lib/format';
import type { BackgroundJob, BackgroundProcess, BackgroundState } from '@/lib/types/activity';

const STATE: Record<BackgroundState, string> = { running: 'Running', late: 'Late', stopped: 'Stopped', not_reported: 'Not reported' };
const TONE: Record<BackgroundState, string> = {
  running: 'border-success/40 bg-success/10 text-success-text',
  late: 'border-warning/40 bg-warning/10 text-warning-text',
  stopped: 'border-destructive/40 bg-destructive/10 text-destructive',
  not_reported: 'text-muted-foreground',
};
const OUTCOME: Record<BackgroundJob['outcome'], string> = { done: 'Done', retried: 'Retried', failed: 'Failed' };
const SERVICE: Record<string, string> = { files: 'Files', documents: 'Documents', tools: 'Tools', agents: 'Agents' };

const fromSeconds = (s: number) => new Date(s * 1000).toISOString();

function every(p: BackgroundProcess): string {
  if (p.everySeconds === null) return 'As work arrives';
  if (p.everySeconds < 1) return `Every ${p.everySeconds * 1000} ms`;
  if (p.everySeconds < 60) return `Every ${plural(p.everySeconds, 'second')}`;
  if (p.everySeconds < 3600) return `Every ${plural(p.everySeconds / 60, 'minute')}`;
  return `Every ${plural(p.everySeconds / 3600, 'hour')}`;
}

function When({ seconds }: { seconds: number | null }) {
  if (seconds === null) return <span className="text-muted-foreground">Never</span>;
  const at = fromSeconds(seconds);
  return (
    <span className="whitespace-nowrap text-muted-foreground tabular-nums" title={dateTime(at)}>
      {relativeTime(at)}
    </span>
  );
}

const PROCESS_COLUMNS: ColumnDef<BackgroundProcess>[] = [
  {
    accessorKey: 'title',
    header: 'Process',
    cell: ({ row }) => (
      <div className="max-w-sm min-w-56">
        <div className="text-sm font-medium">{row.original.title}</div>
        <div className="text-xs whitespace-normal text-muted-foreground">{row.original.does}</div>
      </div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: 'state',
    header: 'State',
    cell: ({ row }) => (
      <Badge variant="outline" className={`font-normal ${TONE[row.original.state]}`} data-testid={`state-${row.original.key}`}>
        {STATE[row.original.state]}
      </Badge>
    ),
    enableHiding: false,
  },
  { accessorKey: 'lastRunAt', header: 'Last run', cell: ({ row }) => <When seconds={row.original.lastRunAt} /> },
  { id: 'every', header: 'Runs', cell: ({ row }) => <span className="whitespace-nowrap">{every(row.original)}</span> },
  { accessorKey: 'doneHour', header: 'Done · last hour', cell: ({ row }) => <span className="tabular-nums">{row.original.doneHour}</span> },
  { accessorKey: 'waiting', header: 'Waiting', cell: ({ row }) => <span className="tabular-nums">{row.original.waiting ?? '—'}</span> },
  {
    accessorKey: 'lastError',
    header: 'Last error',
    cell: ({ row }) =>
      row.original.lastError ? (
        <span className="text-sm text-destructive" title={row.original.lastErrorAt ? dateTime(fromSeconds(row.original.lastErrorAt)) : undefined}>
          {row.original.lastError}
        </span>
      ) : (
        <span className="text-muted-foreground">None</span>
      ),
  },
  { accessorKey: 'service', header: 'Service', cell: ({ row }) => SERVICE[row.original.service] ?? row.original.service },
];

const JOB_COLUMNS: ColumnDef<BackgroundJob>[] = [
  {
    accessorKey: 'summary',
    header: 'What it did',
    cell: ({ row }) => (
      <div className="max-w-md min-w-56">
        <div className="text-sm whitespace-normal">{row.original.summary}</div>
        <div className="text-xs text-muted-foreground">{row.original.processTitle}</div>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'teamName', header: 'Team', cell: ({ row }) => row.original.teamName ?? row.original.teamId },
  {
    accessorKey: 'at',
    header: 'When',
    cell: ({ row }) => (
      <span className="whitespace-nowrap text-muted-foreground tabular-nums" title={dateTime(row.original.at)}>
        {relativeTime(row.original.at)}
      </span>
    ),
  },
  {
    accessorKey: 'outcome',
    header: 'Outcome',
    cell: ({ row }) => (
      <Badge variant="outline" className={`font-normal ${row.original.outcome === 'failed' ? TONE.stopped : row.original.outcome === 'retried' ? TONE.late : TONE.running}`}>
        {OUTCOME[row.original.outcome]}
      </Badge>
    ),
  },
];

/**
 * Govern > Background (c-516): every background process of the account with its heartbeat, and the latest jobs each
 * did and for which team. Read-only, for account admins; agents-service answers anyone else with not found.
 */
export default function BackgroundPage() {
  const query = useBackground();
  const view = query.data;
  return (
    <PageLayout icon={HeartPulse} title="Background" description="Work that runs without a person asking, and what it did for each team">
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={10} />
      ) : query.isError && query.error instanceof ApiError && query.error.status === 404 ? (
        <EmptyState icon={ShieldCheck} title="Only an account admin sees background processes" description="Each team sees its own background jobs in Activity." testId="background-admin-only" />
      ) : query.isError || !view ? (
        <QueryError what="the background processes" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-6">
          {view.unreachable.length > 0 && (
            <Note tone="warning" title={`${view.unreachable.map((s) => SERVICE[s] ?? s).join(', ')} did not answer`}>
              Their processes show as not reported until the next check.
            </Note>
          )}
          <Section title="Processes" description="Each runs once for the account and does each job inside that job's team." flush>
            <DataTableWithViews columns={PROCESS_COLUMNS} data={view.processes} getRowId={(p) => p.key} hideViewSwitcher />
          </Section>
          <Section title="Latest jobs" description={`The newest ${plural(view.jobs.length, 'job')} across every team`} flush>
            <DataTableWithViews
              columns={JOB_COLUMNS}
              data={view.jobs}
              getRowId={(j) => j.id}
              hideViewSwitcher
              emptyState={<EmptyState icon={HeartPulse} title="No jobs yet" description="Jobs show here as the processes do work for a team." />}
            />
          </Section>
        </div>
      )}
    </PageLayout>
  );
}
