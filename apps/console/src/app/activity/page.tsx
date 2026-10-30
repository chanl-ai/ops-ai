'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Activity, RotateCcw, X } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useActivity } from '@/hooks/activity-queries';
import { useRunSetAsideEmail } from '@/hooks/engine-queries';
import { columnFiltersOf, useListParams } from '@/hooks/use-list-params';
import { ACTIVITY_STATUS, activityStatus } from '@/lib/activity-status';
import { relativeTime } from '@/lib/format';
import type { ActivityKind, ActivityRow, ActivityStatus } from '@/lib/types/activity';
import { cn } from '@/lib/utils';

const KIND: Record<ActivityKind, string> = { workflow_run: 'Workflow run', agent_run: 'Agent run', chat: 'Chat', email: 'Email received', decision: 'Human Task decision', tool_call: 'Tool call', case: 'Case', reminder: 'Reminder', system_workflow: 'Shipped workflow update', background: 'Background job' };
const STATUS = ACTIVITY_STATUS;
const TONE: Record<ActivityStatus, string> = { running: '', waiting: 'border-warning/40 bg-warning/10 text-warning-text', done: 'border-success/40 bg-success/10 text-success-text', failed: 'border-destructive/40 bg-destructive/10 text-destructive', skipped: 'text-muted-foreground' };

/** The page a row opens; an email has no page of its own, so its row opens nothing. */
function hrefOf(r: ActivityRow): string | undefined {
  const id = encodeURIComponent(r.ref.id);
  if (r.ref.kind === 'run') return `/workflows/runs/${id}`;
  if (r.ref.kind === 'thread' || r.ref.kind === 'chat') return `/chat/${id}`;
  if (r.ref.kind === 'review') return `/reviews?review=${id}`;
  if (r.ref.kind === 'case') return `/cases/${id}`;
  if (r.ref.kind === 'workflow') return `/workflows/${id}`;
  return undefined;
}

/** Who did it, by name; a run started by another run reads as that run's workflow. */
const actorOf = (r: ActivityRow) => (r.actor.kind === 'trigger' ? `Email to ${r.actor.name}` : r.actor.name);

type Row = ActivityRow & { href?: string; onRowClick?: (r: ActivityRow) => void; onRunAgain?: () => void; rowTestId: string };

const COLUMNS: ColumnDef<Row>[] = [
  {
    accessorKey: 'title',
    header: 'What happened',
    cell: ({ row }) => (
      <span className="min-w-0">
        <span className="block truncate font-medium">{row.original.title}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {KIND[row.original.kind] ?? row.original.kind} · {actorOf(row.original)}
          {activityStatus(row.original).note ? ` · ${activityStatus(row.original).note}` : ''}
        </span>
        {row.original.detail && (
          <span className="block whitespace-normal break-words text-xs text-muted-foreground" data-testid="activity-detail">
            {row.original.detail}
          </span>
        )}
        {/* Narrow screens hide the actions column, so Run again sits under the title instead. */}
        {row.original.onRunAgain && (
          <span className="mt-1 block md:hidden">
            <RunAgainButton onClick={row.original.onRunAgain} />
          </span>
        )}
      </span>
    ),
    enableHiding: false,
  },
  { accessorKey: 'kind', header: 'Kind', cell: ({ row }) => <span data-testid="activity-kind">{KIND[row.original.kind] ?? row.original.kind}</span> },
  {
    accessorKey: 'status',
    header: 'Status',
    cell: ({ row }) => (
      <Badge variant="outline" className={cn('font-normal', TONE[row.original.status])} data-testid="activity-status">
        {activityStatus(row.original).label}
      </Badge>
    ),
  },
  { id: 'source', header: 'Source', cell: ({ row }) => <span className="text-muted-foreground">{row.original.source.name}</span> },
  { accessorKey: 'at', header: 'When', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{relativeTime(row.original.at)}</span> },
  {
    // An email the mail listener set aside after its run failed to start 3 times (c-561).
    id: 'actions',
    header: '',
    enableHiding: false,
    cell: ({ row }) => row.original.onRunAgain && <span className="hidden md:inline"><RunAgainButton onClick={row.original.onRunAgain} /></span>,
  },
];

function RunAgainButton({ onClick }: { onClick: () => void }) {
  return (
    <Button
      variant="outline"
      size="sm"
      data-testid="activity-run-again"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
    >
      <RotateCcw /> Run again
    </Button>
  );
}

/**
 * Activity: everything that happened in the team, from one server list: workflow and agent runs, chats, emails received
 * and Human Task decisions. Channel, agent and workflow pages link here with `?source=<type>:<id>` instead of listing
 * their own; the Audit log stays separate.
 */
export default function ActivityPage() {
  const router = useRouter();
  const params = useSearchParams();
  // A kind's View activity names each of its channels; one source param per channel.
  const sources = params.getAll('source');
  const source = sources[0] ?? null;
  const sourceName = params.get('name');
  // `?kind=email&status=skipped` (a link from a channel or a test) opens the page with those filters chosen.
  const linked = React.useMemo(() => {
    const out: { kind?: string[]; status?: string[] } = {};
    if (params.getAll('kind').length) out.kind = params.getAll('kind');
    if (params.getAll('status').length) out.status = params.getAll('status');
    return out;
  }, [params]);
  const list = useListParams<{ kind?: string[]; status?: string[] }>(undefined, undefined, linked);
  const filters = list.params.filters ?? {};
  const query = useActivity({ page: list.params.page, pageSize: list.params.pageSize, kind: filters.kind, status: filters.status, source: sources.length ? sources : undefined });
  const facets = query.data?.facets ?? {};
  const runAgain = useRunSetAsideEmail();
  const [again, setAgain] = React.useState<ActivityRow | null>(null);
  const rows: Row[] = React.useMemo(
    () =>
      (query.data?.data ?? []).map((r) => {
        const href = hrefOf(r);
        const onRunAgain = r.kind === 'email' && r.outcome === 'set_aside' ? () => setAgain(r) : undefined;
        return { ...r, href, onRowClick: href ? () => router.push(href) : undefined, onRunAgain, rowTestId: `activity-row-${r.id}` };
      }),
    [query.data, router],
  );

  return (
    <PageLayout icon={Activity} title="Activity" description="Everything that happened in the team: runs, chats, emails received and Human Task decisions">
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="activity" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} testId="activity-error" />
      ) : (
        <div className="flex flex-col gap-4">
          {source && (
            <div className="flex items-center gap-2 text-sm" data-testid="activity-source">
              <span className="text-muted-foreground">Showing</span>
              <Badge variant="secondary">{sourceName ?? source.split(':').slice(1).join(':')}</Badge>
              <Button asChild variant="ghost" size="sm">
                <Link href="/activity">
                  <X className="size-3.5" /> Show all
                </Link>
              </Button>
            </div>
          )}
          <DataTableWithViews
            columns={COLUMNS}
            data={rows}
            getRowId={(r) => r.id}
            hideViewSwitcher
            filters={[
              { column: 'kind', title: 'Kind', options: (Object.keys(KIND) as ActivityKind[]).map((k) => ({ label: KIND[k], value: k, count: facets.kind?.[k] ?? 0 })) },
              { column: 'status', title: 'Status', options: (Object.keys(STATUS) as ActivityStatus[]).map((s) => ({ label: STATUS[s], value: s, count: facets.status?.[s] ?? 0 })) },
            ]}
            initialColumnFilters={columnFiltersOf(linked)}
            onColumnFiltersChange={list.onColumnFiltersChange}
            serverPagination={{
              enabled: true,
              total: query.data?.pagination.total ?? 0,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: query.data?.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: query.isFetching && query.isPlaceholderData,
            }}
            emptyState={<ListEmpty icon={Activity} noun="activity" filtered={list.isFiltered || !!source} description="Runs, chats, emails received and decisions appear here as they happen." />}
          />
        </div>
      )}
      <ConfirmActionDialog
        open={!!again}
        onOpenChange={(o) => !o && setAgain(null)}
        title="Run this email again"
        consequence={again ? `Starts the run for "${again.title}" on the workflow's live version, as you. The email keeps its own run key, so it never starts two runs.` : ''}
        details={again ? [{ label: 'From', value: again.actor.name }, { label: 'Mailbox', value: again.source.name }] : undefined}
        runsNow
        note="The run starts as soon as you confirm. If it fails to start again, the email stays set aside and this says why."
        confirmLabel="Run again"
        isPending={runAgain.isPending}
        onConfirm={async () => {
          if (!again) return;
          const started = await runAgain.mutateAsync(again.ref.id);
          toast.success('The email\'s run started', { action: { label: 'Open run', onClick: () => router.push(`/workflows/runs/${encodeURIComponent(started.runId)}`) } });
        }}
      />
    </PageLayout>
  );
}
