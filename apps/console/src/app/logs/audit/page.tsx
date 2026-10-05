'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { AlertCircle, Download, History, KeyRound, Rocket, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { AuditSheet } from '@/components/logs/audit-sheet';
import { ACTION_LABEL, ActionBadge, ActorCell, options, TARGET_LABEL } from '@/components/logs/log-meta';
import { PageLayout } from '@/components/page-layout';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useAudit } from '@/hooks/governance-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useTeam } from '@/hooks/use-team';
import { dateTime, plural, relativeTime } from '@/lib/format';
import type { AuditEntry, AuditFilters, AuditView } from '@/lib/types/governance';

type Row = AuditEntry & { onRowClick: (e: AuditEntry) => void };

function columns(showTeam: boolean): ColumnDef<Row>[] {
  return [
    {
      accessorKey: 'at',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Time" />,
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-muted-foreground tabular-nums" title={dateTime(row.original.at)}>
          {relativeTime(row.original.at)}
        </span>
      ),
    },
    {
      // Holds every searched field so the table's own filter keeps the rows the server matched.
      id: 'summary',
      accessorFn: (r) => `${r.summary} ${r.actor.name} ${r.target.name} ${r.reason ?? ''} ${r.requestId}`,
      header: 'What happened',
      cell: ({ row }) => (
        <div className="max-w-sm min-w-56">
          <div className="flex min-w-0 items-center gap-2">
            <ActionBadge action={row.original.action} />
            <span className="truncate text-sm" title={row.original.summary}>
              {row.original.summary}
            </span>
          </div>
          {row.original.reason && (
            <div className="mt-0.5 truncate text-xs text-muted-foreground" title={row.original.reason}>
              {row.original.reason}
            </div>
          )}
        </div>
      ),
      enableHiding: false,
    },
    { accessorKey: 'action', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
    { id: 'actorKind', accessorFn: (r) => r.actor.kind, header: ({ column }) => <DataTableColumnHeader column={column} title="Actor" />, cell: ({ row }) => <ActorCell {...row.original.actor} />, filterFn: facetFilterFn },
    {
      id: 'targetType',
      accessorFn: (r) => r.target.type,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Target" />,
      cell: ({ row }) => {
        const t = row.original.target;
        return (
          <div className="max-w-52 min-w-40">
            <div className="text-xs text-muted-foreground">{TARGET_LABEL[t.type]}</div>
            {t.href ? (
              <StopRowClick align="start">
                <Link href={t.href} className="block truncate text-sm underline-offset-4 hover:underline" title={t.name}>
                  {t.name}
                </Link>
              </StopRowClick>
            ) : (
              <span className="block truncate text-sm" title={t.name}>
                {t.name}
              </span>
            )}
          </div>
        );
      },
      filterFn: facetFilterFn,
    },
    ...(showTeam ? [{ accessorKey: 'teamId', header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.team}</span>, filterFn: facetFilterFn } as ColumnDef<Row>] : []),
    { accessorKey: 'requestId', header: ({ column }) => <DataTableColumnHeader column={column} title="Request id" />, cell: ({ row }) => <code className="font-mono text-xs text-muted-foreground">{row.original.requestId}</code> },
  ];
}

const VIEWS: { id: AuditView; label: string; icon?: typeof Rocket }[] = [
  { id: 'all', label: 'All' },
  { id: 'publishes', label: 'Publishes and approvals', icon: Rocket },
  { id: 'access', label: 'Access changes', icon: KeyRound },
  { id: 'deletions', label: 'Deletions', icon: Trash2 },
];

export default function AuditPage() {
  const { team, teams } = useTeam();
  const showTeam = team?.scope === 'all';
  const [view, setView] = React.useState<AuditView>('all');
  const list = useListParams<AuditFilters>('summary', 20);
  const query = useAudit({ ...list.params, view });
  const [activeId, setActiveId] = React.useState<string | null>(null);

  const entries = query.data?.data ?? [];
  const index = entries.findIndex((e) => e.id === activeId);
  const active = index >= 0 ? entries[index] : null;
  const rows: Row[] = React.useMemo(() => entries.map((e) => ({ ...e, onRowClick: (x: AuditEntry) => setActiveId(x.id) })), [entries]);
  const cols = React.useMemo(() => columns(showTeam), [showTeam]);
  const counts = query.data?.viewCounts;
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, opts: { label: string; value: string }[]) => opts.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 })).filter((o) => o.count > 0 || column === 'action');

  const exportCsv = () =>
    toast.success('Export started', {
      description: `${plural(query.data?.pagination.total ?? 0, 'entry', 'entries')} in this view, as CSV. A download link will be emailed to you.`,
    });

  return (
    <PageLayout
      icon={History}
      title="Audit log"
      description="Who changed what: publishes, approvals, access, settings and sign-ins"
      actions={
        <Button variant="outline" onClick={exportCsv} disabled={!query.data?.pagination.total}>
          <Download className="size-4" /> Export
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton tableRows={10} />
      ) : query.isError && !query.data ? (
        <QueryError what="the audit log" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          {query.isError && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription className="flex items-center justify-between gap-2">
                Refreshing the log failed. These are the last results that loaded.
                <Button size="sm" variant="outline" onClick={() => query.refetch()}>
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <SavedViewTabs
            ariaLabel="Audit views"
            presets={VIEWS.map((v) => ({ id: v.id, label: `${v.label} · ${counts?.[v.id] ?? 0}`, icon: v.icon }))}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as AuditView);
              list.reset();
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />

          <DataTableWithViews
            columns={cols}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="summary"
            searchPlaceholder="Search people, targets, reasons or request ids…"
            initialColumnVisibility={{ requestId: false }}
            filters={[
              { column: 'action', title: 'Action', options: withCounts('action', options(ACTION_LABEL)) },
              { column: 'targetType', title: 'Target', options: withCounts('targetType', options(TARGET_LABEL)) },
              { column: 'actorKind', title: 'Actor', options: withCounts('actorKind', [{ value: 'person', label: 'Person' }, { value: 'workflow', label: 'Workflow identity' }]) },
              ...(showTeam ? [{ column: 'teamId', title: 'Team', options: withCounts('teamId', teams.map((t) => ({ value: t.id, label: t.name }))) }] : []),
            ]}
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
            emptyState={
              <ListEmpty
                icon={History}
                noun={view === 'all' ? 'entries' : VIEWS.find((v) => v.id === view)!.label.toLowerCase()}
                filtered={list.isFiltered}
                description="Changes to workflows, agents, access and settings in this team are recorded here."
              />
            }
          />
        </div>
      )}

      <AuditSheet
        entry={active}
        onOpenChange={(o) => !o && setActiveId(null)}
        navigation={
          active
            ? {
                currentIndex: index,
                totalCount: entries.length,
                onPrev: index > 0 ? () => setActiveId(entries[index - 1].id) : undefined,
                onNext: index < entries.length - 1 ? () => setActiveId(entries[index + 1].id) : undefined,
              }
            : undefined
        }
      />
    </PageLayout>
  );
}
