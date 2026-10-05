'use client';

import * as React from 'react';
import type { ColumnDef, ColumnFiltersState } from '@tanstack/react-table';
import { AlertTriangle, CalendarPlus, CalendarX, KeyRound, ShieldOff } from 'lucide-react';

import { ExpiryText, GRANT_STATUS_LABEL, RESOURCE_KIND_LABEL, SCOPE_LABEL, ScopeBadge } from '@/components/access/access-meta';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { options } from '@/components/logs/log-meta';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { selectColumn } from '@/components/shared/select-column';
import { useExtendGrants, useGrants, useRevokeGrants } from '@/hooks/governance-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { plural, relativeTime } from '@/lib/format';
import type { AccessGrant, GrantFilters, GrantView } from '@/lib/types/governance';

type Row = AccessGrant;

const REVOKE_REASONS = ['No longer needed', 'Pilot ended', 'Security review finding', 'Workflow retired', 'Granted in error'];
const EXTEND = ['30 days', '90 days', '180 days'];

function columns(onRevoke: (g: AccessGrant) => void, onExtend: (g: AccessGrant) => void): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((g) => g.resource),
    {
      // Holds every searched field so the table's own filter keeps the rows the server matched.
      id: 'resource',
      accessorFn: (r) => `${r.resource} ${r.workflowName} ${r.grantedBy} ${r.reason ?? ''}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Access to" />,
      cell: ({ row }) => (
        <div className="min-w-52">
          <div className="text-sm font-medium">{row.original.resourceKind === 'module' ? <code className="font-mono text-[13px]">{row.original.resource}</code> : row.original.resource}</div>
          <div className="text-xs text-muted-foreground">{RESOURCE_KIND_LABEL[row.original.resourceKind]}</div>
        </div>
      ),
      enableHiding: false,
    },
    { accessorKey: 'resourceKind', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
    { accessorKey: 'workflowId', header: ({ column }) => <DataTableColumnHeader column={column} title="Workflow" />, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.workflowName}</span>, filterFn: facetFilterFn },
    { accessorKey: 'scope', header: ({ column }) => <DataTableColumnHeader column={column} title="Scope" />, cell: ({ row }) => <ScopeBadge scope={row.original.scope} />, filterFn: facetFilterFn },
    { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Expires" />, cell: ({ row }) => <ExpiryText expiresAt={row.original.expiresAt} status={row.original.status} />, filterFn: facetFilterFn },
    {
      accessorKey: 'grantedBy',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Granted by" />,
      cell: ({ row }) => (
        <div className="min-w-32">
          <div className="text-sm">{row.original.grantedBy}</div>
          <div className="text-xs text-muted-foreground">{relativeTime(row.original.grantedAt)}</div>
        </div>
      ),
    },
    { accessorKey: 'reason', header: ({ column }) => <DataTableColumnHeader column={column} title="Reason" />, cell: ({ row }) => <span className="line-clamp-2 min-w-40 text-xs text-muted-foreground">{row.original.reason ?? '—'}</span> },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Extend', icon: CalendarPlus, onClick: (r: { original: AccessGrant }) => onExtend(r.original) },
              { label: 'Revoke', icon: ShieldOff, variant: 'destructive' as const, onClick: (r: { original: AccessGrant }) => onRevoke(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

/** Every grant held by this team's workflow identities, with the expiring view and revoke/extend in bulk. */
export function GrantsTab({ workflowId, onClearWorkflow }: { workflowId?: string; onClearWorkflow: () => void }) {
  const [view, setView] = React.useState<GrantView>('all');
  const list = useListParams<GrantFilters>('resource');
  const query = useGrants({ ...list.params, view });
  const revoke = useRevokeGrants();
  const extend = useExtendGrants();
  const [bulk, setBulk] = React.useState<{ kind: 'revoke' | 'extend'; rows: AccessGrant[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const cols = React.useMemo(() => columns((g) => setBulk({ kind: 'revoke', rows: [g] }), (g) => setBulk({ kind: 'extend', rows: [g] })), []);

  const counts = query.data?.viewCounts;
  const facets = query.data?.facets ?? {};
  const data = query.data?.data ?? [];
  const withCounts = (column: string, opts: { label: string; value: string }[]) => opts.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const workflowOptions = React.useMemo(() => {
    const seen = new Map<string, string>();
    for (const g of data) seen.set(g.workflowId, g.workflowName);
    for (const id of Object.keys(facets.workflowId ?? {})) if (!seen.has(id)) seen.set(id, id);
    return [...seen].map(([value, label]) => ({ value, label }));
  }, [data, facets.workflowId]);
  const { onColumnFiltersChange } = list;
  // Clearing the workflow filter that arrived from an identity also clears it from the URL.
  const onFilters = React.useCallback(
    (f: ColumnFiltersState) => {
      onColumnFiltersChange(f);
      if (workflowId && !f.some((x) => x.id === 'workflowId')) onClearWorkflow();
    },
    [onColumnFiltersChange, workflowId, onClearWorkflow],
  );
  const label = (id: string) => shown?.rows.find((g) => g.id === id)?.resource ?? id;
  const names = (shown?.rows ?? []).map((g) => `${g.workflowName} → ${g.resource}${g.status === 'expired' ? ' (expired)' : ''}`);
  const expiredSelected = (shown?.rows ?? []).filter((g) => g.status === 'expired');

  if (query.isPending) return <PageSkeleton statCards={0} viewTabs={3} tableRows={8} />;
  if (query.isError && !query.data) return <QueryError what="access grants" onRetry={() => query.refetch()} retrying={query.isFetching} />;

  return (
    <div className="flex flex-col gap-4">
      <SavedViewTabs
        ariaLabel="Grant views"
        presets={[
          { id: 'all', label: `All grants · ${counts?.all ?? 0}`, icon: KeyRound },
          { id: 'expiring', label: `Expiring soon · ${counts?.expiring ?? 0}`, icon: AlertTriangle },
          { id: 'expired', label: `Expired · ${counts?.expired ?? 0}`, icon: CalendarX },
        ]}
        savedViews={[]}
        activePresetId={view}
        activeSavedViewId={null}
        onSelectPreset={(id) => {
          setView(id as GrantView);
          list.reset();
          setResetKey((k) => k + 1);
        }}
        onSelectSavedView={() => undefined}
        onSaveView={() => undefined}
        onDeleteView={() => undefined}
        canSave={false}
      />
      <DataTableWithViews
        key={workflowId ?? 'all'}
        columns={cols}
        data={data}
        getRowId={(r) => r.id}
        searchColumn="resource"
        searchPlaceholder="Search modules, knowledge bases, workflows or reasons…"
        initialColumnFilters={workflowId ? [{ id: 'workflowId', value: [workflowId] }] : undefined}
        initialColumnVisibility={{ reason: false }}
        filters={[
          { column: 'workflowId', title: 'Workflow', options: withCounts('workflowId', workflowOptions) },
          { column: 'resourceKind', title: 'Kind', options: withCounts('resourceKind', options(RESOURCE_KIND_LABEL)) },
          { column: 'scope', title: 'Scope', options: withCounts('scope', options(SCOPE_LABEL)) },
          { column: 'status', title: 'Status', options: withCounts('status', options(GRANT_STATUS_LABEL)) },
        ]}
        onColumnFiltersChange={onFilters}
        selectionResetKey={resetKey}
        bulkActions={[
          { label: 'Extend', icon: CalendarPlus, variant: 'outline', onClick: (rows) => setBulk({ kind: 'extend', rows }) },
          { label: 'Revoke', icon: ShieldOff, variant: 'destructive', onClick: (rows) => setBulk({ kind: 'revoke', rows }) },
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
            icon={KeyRound}
            noun={view === 'expiring' ? 'grants expiring soon' : view === 'expired' ? 'expired grants' : 'grants'}
            filtered={list.isFiltered}
            description={
              view === 'expiring' ? 'Nothing expires in the next 14 days.' : view === 'expired' ? 'No grants have lapsed.' : 'Grant a workflow access to a system module or knowledge base.'
            }
          />
        }
      />

      <BulkFieldDialog
        open={bulk?.kind === 'revoke'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={shown?.rows.length === 1 ? 'Revoke access' : `Revoke ${shown?.rows.length ?? 0} grants`}
        description="Takes effect at once: the next call to these is denied, and runs waiting on approval for them fail. The reason is kept in the audit log."
        fieldLabel="Reason"
        options={REVOKE_REASONS}
        names={names}
        confirmLabel="Revoke"
        destructive
        isPending={revoke.isPending}
        onConfirm={async (reason) => {
          const res = await revoke.mutateAsync({ ids: bulk!.rows.map((g) => g.id), reason });
          toastBulk(res, 'Revoked', 'grant', label);
          setResetKey((k) => k + 1);
        }}
      />
      <BulkFieldDialog
        open={bulk?.kind === 'extend'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={shown?.rows.length === 1 ? 'Extend access' : `Extend ${shown?.rows.length ?? 0} grants`}
        description="Sets a new expiry counted from today. Grants that never expire are skipped; money movement is capped at 180 days."
        fieldLabel="Extend by"
        prompt="Choose how long to extend"
        options={EXTEND}
        names={names}
        notice={
          expiredSelected.length
            ? `${plural(expiredSelected.length, 'selected grant')} ${expiredSelected.length === 1 ? 'has' : 'have'} expired. Extending reactivates ${expiredSelected.length === 1 ? 'it' : 'them'}, so the workflow can call ${expiredSelected.length === 1 ? 'it' : 'them'} again from now.`
            : undefined
        }
        confirmLabel="Extend"
        isPending={extend.isPending}
        onConfirm={async (v) => {
          const res = await extend.mutateAsync({ ids: bulk!.rows.map((g) => g.id), days: parseInt(v, 10) });
          toastBulk(res, expiredSelected.length === shown?.rows.length ? 'Reactivated' : 'Extended', 'grant', label);
          setResetKey((k) => k + 1);
        }}
      />
    </div>
  );
}
