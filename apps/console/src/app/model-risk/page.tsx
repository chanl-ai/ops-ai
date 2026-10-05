'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { AlertTriangle, Bot, CalendarClock, CalendarDays, ClipboardCheck, Route, Scale, ShieldAlert } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { NextReviewDialog, RequestValidationDialog } from '@/components/model-risk/model-risk-dialogs';
import { TYPE_LABEL, VALIDATION_STATUS_LABEL, ValidationBadge } from '@/components/model-risk/model-risk-meta';
import { PageLayout } from '@/components/page-layout';
import { toastBulk } from '@/components/shared/bulk';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { selectColumn } from '@/components/shared/select-column';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { RiskBadge } from '@/components/status-badges';
import { useModelRisk, useRequestValidation, useSetNextReview } from '@/hooks/model-risk-queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { dateOnly, pct, plural } from '@/lib/format';
import type { Risk } from '@/lib/types/domain';
import type { ModelEntry, ModelRiskFilters, ModelRiskView } from '@/lib/types/model-risk';

type Row = ModelEntry & { onRowClick: (e: ModelEntry) => void; href: string; rowTestId: string };

const TIER_ORDER: Record<Risk, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const TIER_OPTIONS = (['critical', 'high', 'medium', 'low'] as const).map((v) => ({ value: v, label: v[0].toUpperCase() + v.slice(1) }));
const STATUS_OPTIONS = Object.entries(VALIDATION_STATUS_LABEL).map(([value, label]) => ({ value, label }));
const TYPE_OPTIONS = [
  { value: 'workflow', label: 'Workflow', icon: Route },
  { value: 'agent', label: 'Agent', icon: Bot },
];

const columns: ColumnDef<Row>[] = [
  selectColumn<Row>((e) => e.name),
  {
    id: 'name',
    accessorFn: (e) => e.name,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Model" />,
    cell: ({ row }) => {
      const Icon = row.original.type === 'agent' ? Bot : Route;
      return (
        <div className="flex w-52 max-w-52 items-center gap-2.5" title={row.original.name}>
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <div className="truncate font-medium">{row.original.name}</div>
            <div className="text-xs text-muted-foreground">{TYPE_LABEL[row.original.type]}</div>
          </div>
        </div>
      );
    },
    enableHiding: false,
  },
  { accessorKey: 'type', header: 'Type', cell: ({ row }) => TYPE_LABEL[row.original.type], filterFn: facetFilterFn },
  {
    accessorKey: 'ownerTeam',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Owner team" />,
    cell: ({ row }) => (
      <div className="max-w-36 text-xs" title={`${row.original.ownerTeam} · ${row.original.owner}`}>
        <div className="truncate">{row.original.ownerTeam}</div>
        {row.original.owner !== row.original.ownerTeam && <div className="truncate text-muted-foreground">{row.original.owner}</div>}
      </div>
    ),
    filterFn: facetFilterFn,
  },
  {
    id: 'model',
    accessorFn: (e) => e.model,
    header: 'Model',
    cell: ({ row }) => (
      <div className="whitespace-nowrap text-xs">
        <code className="font-mono">{row.original.model}</code>
        <div className="text-muted-foreground">
          {row.original.provider} · alias <code className="font-mono">{row.original.alias}</code>
        </div>
      </div>
    ),
  },
  { accessorKey: 'provider', header: 'Provider', filterFn: facetFilterFn },
  {
    accessorKey: 'tier',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Risk tier" />,
    cell: ({ row }) => <RiskBadge risk={row.original.tier} />,
    sortingFn: (a, b) => TIER_ORDER[a.original.tier] - TIER_ORDER[b.original.tier],
    filterFn: facetFilterFn,
  },
  {
    accessorKey: 'validationStatus',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Validation" />,
    cell: ({ row }) => (
      <div className="flex max-w-40 flex-col items-start gap-1">
        <ValidationBadge status={row.original.validationStatus} wrap />
        {row.original.openReview?.scope === 'tier_change' && <span className="text-xs text-sky-700 dark:text-sky-300">Tier change open</span>}
      </div>
    ),
    filterFn: facetFilterFn,
  },
  {
    accessorKey: 'nextReviewAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Next review" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-xs tabular-nums">{row.original.nextReviewAt ? dateOnly(row.original.nextReviewAt) : '—'}</span>,
    sortUndefined: 'last',
  },
  {
    accessorKey: 'openFindings',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Open findings" />,
    cell: ({ row }) => <span className={row.original.openFindings ? 'font-medium text-amber-700 tabular-nums dark:text-amber-400' : 'tabular-nums text-muted-foreground'}>{row.original.openFindings}</span>,
  },
  {
    accessorKey: 'lastEvalPassRate',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Last eval" />,
    cell: ({ row }) => <span className="tabular-nums">{row.original.lastEvalPassRate === null ? '—' : pct(row.original.lastEvalPassRate)}</span>,
    sortUndefined: 'last',
  },
];

export default function ModelRiskPage() {
  const router = useRouter();
  const [view, setView] = React.useState<ModelRiskView>('all');
  const list = useListParams<ModelRiskFilters>('name');
  const query = useModelRisk({ ...list.params, view });
  const request = useRequestValidation();
  const nextReview = useSetNextReview();
  const [bulk, setBulk] = React.useState<{ kind: 'validate' | 'review'; rows: ModelEntry[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const names = (shown?.rows ?? []).map((e) => e.name);
  const nameOf = (id: string) => shown?.rows.find((e) => e.id === id)?.name ?? id;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };

  const rows: Row[] = React.useMemo(
    () => (query.data?.data ?? []).map((e) => ({ ...e, href: `/model-risk/${e.id}`, onRowClick: (x: ModelEntry) => router.push(`/model-risk/${x.id}`), rowTestId: `model-row-${e.id}` })),
    [query.data, router],
  );
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, options: { value: string; label: string }[]) => options.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const counts = query.data?.viewCounts;
  const stats = query.data?.stats;
  const teams = Object.keys(facets.ownerTeam ?? {}).sort();
  const providers = Object.keys(facets.provider ?? {}).sort();

  return (
    <PageLayout icon={Scale} title="Model risk" description="Every agent and workflow as a model: its risk tier, independent validation, conditions and findings">
      {query.isPending ? (
        <PageSkeleton statCards={4} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="the model inventory" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            <StatCard label="Models" value={stats?.total} icon={Scale} footer={{ text: `${stats?.highOrCritical ?? 0} high or critical`, subtext: 'Agents and workflows' }} />
            <StatCard label="Needs validation" value={stats?.notValidated} icon={ShieldAlert} footer={{ text: 'Not validated or in validation', subtext: 'Second line: Model Risk' }} />
            <StatCard label="Review due in 30 days" value={stats?.dueIn30d} icon={CalendarClock} footer={{ text: `${counts?.expired ?? 0} expired`, subtext: 'Validations past their review date' }} />
            <StatCard label="Open findings" value={stats?.openFindings} icon={AlertTriangle} footer={{ text: `${plural(counts?.open_findings ?? 0, 'model')} affected`, subtext: 'Open or remediating' }} />
          </StatCardGrid>

          <SavedViewTabs
            ariaLabel="Model views"
            presets={[
              { id: 'all', label: `All · ${counts?.all ?? 0}` },
              { id: 'needs_validation', label: `Needs validation · ${counts?.needs_validation ?? 0}`, icon: ShieldAlert },
              { id: 'due_30d', label: `Due for review in 30 days · ${counts?.due_30d ?? 0}`, icon: CalendarClock },
              { id: 'open_findings', label: `With open findings · ${counts?.open_findings ?? 0}`, icon: AlertTriangle },
              { id: 'expired', label: `Expired · ${counts?.expired ?? 0}` },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as ModelRiskView);
              list.reset();
              setResetKey((k) => k + 1);
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />

          <DataTableWithViews
            columns={columns}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="name"
            searchPlaceholder="Search models…"
            initialColumnVisibility={{ type: false, provider: false, model: false, lastEvalPassRate: false }}
            filters={[
              { column: 'type', title: 'Type', options: withCounts('type', TYPE_OPTIONS) },
              { column: 'tier', title: 'Risk tier', options: withCounts('tier', TIER_OPTIONS) },
              { column: 'validationStatus', title: 'Validation', options: withCounts('validationStatus', STATUS_OPTIONS) },
              { column: 'ownerTeam', title: 'Owner team', options: withCounts('ownerTeam', teams.map((t) => ({ value: t, label: t }))) },
              { column: 'provider', title: 'Provider', options: withCounts('provider', providers.map((t) => ({ value: t, label: t }))) },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            selectionResetKey={resetKey}
            bulkActions={[
              { label: 'Request validation', icon: ClipboardCheck, variant: 'outline', onClick: (r) => setBulk({ kind: 'validate', rows: r }) },
              { label: 'Set next review', icon: CalendarDays, variant: 'outline', onClick: (r) => setBulk({ kind: 'review', rows: r }) },
            ]}
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
                icon={Scale}
                noun={view === 'all' ? 'models' : 'models in this view'}
                filtered={list.isFiltered}
                description={view === 'all' ? 'Agents and workflows appear here as soon as they are created.' : 'Nothing matches this view right now.'}
              />
            }
          />
        </div>
      )}

      <RequestValidationDialog
        open={bulk?.kind === 'validate'}
        onOpenChange={(o) => !o && setBulk(null)}
        names={names}
        isPending={request.isPending}
        onSubmit={async (note) => {
          const res = await request.mutateAsync({ ids: bulk!.rows.map((e) => e.id), note: note || undefined });
          toastBulk(res, 'Requested validation of', 'model', nameOf);
          finish();
        }}
      />
      <NextReviewDialog
        open={bulk?.kind === 'review'}
        onOpenChange={(o) => !o && setBulk(null)}
        names={names}
        isPending={nextReview.isPending}
        onSubmit={async (date) => {
          const res = await nextReview.mutateAsync({ ids: bulk!.rows.map((e) => e.id), date });
          toastBulk(res, 'Rescheduled', 'model', nameOf);
          finish();
        }}
      />
    </PageLayout>
  );
}
