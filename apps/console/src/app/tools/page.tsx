'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Activity, AlertTriangle, ArrowRight, Boxes, CalendarClock, CalendarX, Clock, Landmark, Plus, ShieldAlert, Trash2, Wrench } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { selectColumn } from '@/components/shared/select-column';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { AddModuleDialog } from '@/components/tools/add-module-dialog';
import { CatalogGrid } from '@/components/tools/catalog-grid';
import { AccessClasses, APPROVAL_STATE_LABEL, ApprovalStateBadge, errorTone, ExpiryText, MODULE_TYPE, ModuleMark, ModuleTypeBadge, pctText } from '@/components/tools/module-meta';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useBulkDeleteModules, useCreateModule, useDeleteModule, useDiscoverModule, useToolCatalog, useToolModules } from '@/hooks/tool-module-queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useTabParam } from '@/hooks/use-tab-param';
import { count, plural } from '@/lib/format';
import type { CatalogItem, ModuleFilters, ModuleView, ToolModule } from '@/lib/types/tool-modules';

type Row = ToolModule & { onRowClick: (m: ToolModule) => void };

const TABS = ['modules', 'catalog'] as const;
const VIEW_EMPTY: Record<ModuleView, string> = {
  all: 'Connect a system once; workflows then request the operations they need.',
  needs_approval: 'Every module has a decided security review and no open requests.',
  expiring: 'No workflow approval expires in the next 30 days.',
  expired: 'No module has only expired approvals.',
  failing: 'Every module is reachable and under a 2% error rate.',
};

function columns(onDelete: (m: ToolModule) => void): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((m) => m.displayName),
    {
      // Holds every searched field so the table's own filter keeps the rows the server matched.
      id: 'displayName',
      accessorFn: (m) => `${m.displayName} ${m.name} ${m.system} ${m.description} ${m.ownerTeam}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Module" />,
      cell: ({ row }) => (
        <div className="flex w-56 max-w-56 items-center gap-3" title={`${row.original.displayName} · ${row.original.system} · Owner ${row.original.ownerTeam}`}>
          <ModuleMark name={row.original.displayName} />
          <div className="min-w-0">
            <div className="truncate font-medium">{row.original.displayName}</div>
            <div className="truncate text-xs text-muted-foreground">Owner {row.original.ownerTeam}</div>
          </div>
        </div>
      ),
      enableHiding: false,
    },
    { accessorKey: 'type', header: ({ column }) => <DataTableColumnHeader column={column} title="Type" />, cell: ({ row }) => <ModuleTypeBadge type={row.original.type} />, filterFn: facetFilterFn },
    {
      accessorKey: 'version',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />,
      cell: ({ row }) => (
        <span className="font-mono text-xs whitespace-nowrap">
          v{row.original.version}
          {row.original.status === 'in_review' && <span className="ml-1 font-sans text-muted-foreground">in review</span>}
        </span>
      ),
    },
    { accessorKey: 'operationCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Operations" />, cell: ({ row }) => <span className="tabular-nums">{row.original.operationCount}</span> },
    {
      id: 'access',
      accessorFn: (m) => m.accessClasses.join(' '),
      header: ({ column }) => <DataTableColumnHeader column={column} title="Access" />,
      cell: ({ row }) => <AccessClasses access={row.original.accessClasses} />,
      filterFn: (r, id, value: string[]) => !value?.length || value.some((v) => String(r.getValue(id)).split(' ').includes(v)),
    },
    {
      accessorKey: 'approvalState',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Approval" />,
      cell: ({ row }) => {
        const m = row.original;
        return (
          <div className="flex max-w-44 flex-col items-start gap-0.5">
            <ApprovalStateBadge state={m.approvalState} />
            {m.drift ? (
              <span className="text-xs text-amber-700 dark:text-amber-400">Server tools changed</span>
            ) : m.status !== 'published' ? (
              <span className="text-xs text-muted-foreground">{m.status === 'draft' ? 'Security review not requested' : 'Security review open'}</span>
            ) : m.pendingApprovals ? (
              <span className="text-xs text-amber-700 dark:text-amber-400">{plural(m.pendingApprovals, 'request')} waiting</span>
            ) : (
              m.nextExpiry && <ExpiryText at={m.nextExpiry} />
            )}
          </div>
        );
      },
      filterFn: facetFilterFn,
    },
    {
      id: 'workflows',
      accessorFn: (m) => m.workflows.length,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Workflows" />,
      cell: ({ row }) => {
        const w = row.original.workflows;
        if (!w.length) return <span className="text-xs text-muted-foreground">None</span>;
        return (
          <span className="block max-w-40 truncate text-sm" title={w.map((x) => x.name).join(', ')}>
            {w[0].name}
            {w.length > 1 && <span className="text-muted-foreground"> +{w.length - 1}</span>}
          </span>
        );
      },
    },
    { accessorKey: 'calls24h', header: ({ column }) => <DataTableColumnHeader column={column} title="Calls · 24h" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.calls24h)}</span> },
    {
      accessorKey: 'errorRate',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Errors" />,
      cell: ({ row }) =>
        !row.original.reachable ? (
          <span className="text-xs font-medium text-red-600 dark:text-red-400">Unreachable</span>
        ) : row.original.calls24h ? (
          <span className={`tabular-nums ${errorTone(row.original.errorRate)}`}>{pctText(row.original.errorRate)}</span>
        ) : (
          <span className="text-xs text-muted-foreground">No calls</span>
        ),
    },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Open', icon: ArrowRight, onClick: (r) => r.original.onRowClick(r.original) },
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => onDelete(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function ToolsPage() {
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'modules');
  const [view, setView] = React.useState<ModuleView>('all');
  const list = useListParams<ModuleFilters>('displayName');
  const query = useToolModules({ ...list.params, view });
  const catalog = useToolCatalog(tab === 'catalog');
  const discover = useDiscoverModule();
  const create = useCreateModule();
  const remove = useDeleteModule();
  const bulkRemove = useBulkDeleteModules();
  const [adding, setAdding] = React.useState<{ item: CatalogItem | null } | null>(null);
  const [deleting, setDeleting] = React.useState<ToolModule | null>(null);
  const [bulk, setBulk] = React.useState<ToolModule[] | null>(null);
  const shownBulk = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const [filterResetKey, setFilterResetKey] = React.useState(0);

  const modules = query.data?.data ?? [];
  const stats = query.data?.stats;
  const counts = query.data?.viewCounts;
  const facets = query.data?.facets ?? {};
  const cols = React.useMemo(() => columns(setDeleting), []);
  const rows: Row[] = React.useMemo(() => modules.map((m) => ({ ...m, onRowClick: (x: ToolModule) => router.push(`/tools/${x.id}`) })), [modules, router]);
  const bulkNames = (shownBulk ?? []).map((m) => m.displayName);

  return (
    <PageLayout
      icon={Wrench}
      title="Tools & MCP"
      description="Systems connected through the data gateway, the operations each exposes, and which workflows may call them"
      actions={
        <Button onClick={() => setAdding({ item: null })}>
          <Plus className="size-4" /> Add module
        </Button>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as (typeof TABS)[number])}>
          <TabsList>
            <TabsTrigger value="modules">Modules</TabsTrigger>
            <TabsTrigger value="catalog">Catalog</TabsTrigger>
          </TabsList>
        </Tabs>
      }
    >
      {tab === 'catalog' ? (
        catalog.isPending ? (
          <PageSkeleton statCards={0} tableRows={6} showToolbar={false} />
        ) : catalog.isError ? (
          <QueryError what="the catalog" onRetry={() => catalog.refetch()} retrying={catalog.isFetching} error={catalog.error} />
        ) : catalog.data.length ? (
          <CatalogGrid items={catalog.data} onAdd={(item) => setAdding({ item })} />
        ) : (
          <ListEmpty icon={Boxes} noun="catalog systems" filtered={false} description="The catalog is empty. Add a module from an MCP server, an OpenAPI spec or an HTTP operation." createLabel="Add module" onCreate={() => setAdding({ item: null })} />
        )
      ) : query.isPending ? (
        <PageSkeleton statCards={4} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="modules" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            <StatCard label="Modules" value={stats?.modules} icon={Boxes} footer={{ text: `${plural(stats?.operations ?? 0, 'operation')}`, subtext: 'Across every module you can see' }} />
            <StatCard label="Calls · 24h" value={stats ? count(stats.calls24h) : undefined} icon={Activity} footer={{ text: `${pctText(stats?.errorRate ?? 0)} failed`, subtext: 'Through the data gateway' }} />
            <StatCard label="Money operations" value={stats?.moneyOperations} icon={Landmark} footer={{ text: 'A person approves every call', subtext: 'And a second person checks it' }} />
            <StatCard label="Expiring soon" value={stats?.expiringModules} icon={CalendarClock} footer={{ text: `${plural(stats?.expiringApprovals ?? 0, 'approval')} within 30 days`, subtext: `${plural(counts?.expired ?? 0, 'module')} already expired` }} />
          </StatCardGrid>
          <SavedViewTabs
            ariaLabel="Module views"
            presets={[
              { id: 'all', label: `All · ${counts?.all ?? 0}`, icon: Boxes },
              { id: 'needs_approval', label: `Needs approval · ${counts?.needs_approval ?? 0}`, icon: ShieldAlert },
              { id: 'expiring', label: `Expiring soon · ${counts?.expiring ?? 0}`, icon: Clock },
              { id: 'expired', label: `Expired · ${counts?.expired ?? 0}`, icon: CalendarX },
              { id: 'failing', label: `Failing · ${counts?.failing ?? 0}`, icon: AlertTriangle },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as ModuleView);
              list.reset();
              setResetKey((k) => k + 1);
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
            initialColumnVisibility={{ type: false, version: false, calls24h: false }}
            searchColumn="displayName"
            searchPlaceholder="Search modules or systems…"
            filters={[
              { column: 'type', title: 'Type', options: (['mcp', 'openapi', 'http', 'code'] as const).map((t) => ({ label: MODULE_TYPE[t].label, value: t, count: facets.type?.[t] ?? 0 })) },
              { column: 'access', title: 'Access', options: [{ label: 'Read', value: 'read' }, { label: 'Write', value: 'write' }, { label: 'Moves money', value: 'money_movement' }].map((o) => ({ ...o, count: facets.access?.[o.value] ?? 0 })) },
              { column: 'approvalState', title: 'Approval', options: (['draft', 'approved', 'needs_approval', 'expiring', 'expired'] as const).map((s) => ({ label: APPROVAL_STATE_LABEL[s], value: s, count: facets.approvalState?.[s] ?? 0 })) },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            selectionResetKey={resetKey}
            filterResetKey={filterResetKey}
            bulkActions={[{ label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (rs) => setBulk(rs) }]}
            serverPagination={{
              enabled: true,
              total: query.data?.pagination.total ?? 0,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: query.data?.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: query.isFetching && query.isPlaceholderData,
            }}
            emptyState={<ListEmpty icon={Boxes} noun={view === 'all' ? 'modules' : 'modules in this view'} filtered={list.isFiltered} onClear={() => setFilterResetKey((k) => k + 1)} description={VIEW_EMPTY[view]} createLabel={view === 'all' ? 'Add module' : undefined} onCreate={view === 'all' ? () => setAdding({ item: null }) : undefined} />}
          />
        </div>
      )}

      <AddModuleDialog
        open={!!adding}
        onOpenChange={(o) => !o && setAdding(null)}
        catalogItem={adding?.item}
        onDiscover={(s) => discover.mutateAsync(s)}
        discovering={discover.isPending}
        creating={create.isPending}
        onCreate={async (input) => {
          const m = await create.mutateAsync(input);
          toast.success(`Saved ${m.displayName} as a draft`, { description: 'Request a security review from its Approval tab.' });
          setAdding(null);
          router.push(`/tools/${m.id}`);
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="module"
        entityName={deleting?.displayName}
        requireNameConfirmation={!!deleting?.operationCount}
        description={deleting ? `Its ${plural(deleting.operationCount, 'operation')} are removed from every agent that holds them.${deleting.workflows.length ? ` ${plural(deleting.workflows.length, 'workflow')} still ${deleting.workflows.length === 1 ? 'holds an approval' : 'hold approvals'}; revoke ${deleting.workflows.length === 1 ? 'it' : 'them'} first.` : ''}` : undefined}
        isLoading={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await remove.mutateAsync(deleting.id);
            toast.success(`Deleted ${deleting.displayName}`);
            setDeleting(null);
          } catch (e) {
            toast.error(`Couldn’t delete ${deleting.displayName}`, { description: (e as Error).message });
          }
        }}
      />
      <DeleteDialog
        open={!!bulk}
        onOpenChange={(o) => !o && setBulk(null)}
        entityType="module"
        count={bulkNames.length}
        description="Modules a workflow still holds an approval for are skipped; revoke those approvals first."
        isLoading={bulkRemove.isPending}
        onConfirm={async () => {
          const res = await bulkRemove.mutateAsync(bulk!.map((m) => m.id));
          toastBulk(res, 'Deleted', 'module', (id) => shownBulk?.find((m) => m.id === id)?.displayName ?? id);
          setBulk(null);
          setResetKey((k) => k + 1);
        }}
      >
        <SelectedList names={bulkNames} />
      </DeleteDialog>
    </PageLayout>
  );
}
