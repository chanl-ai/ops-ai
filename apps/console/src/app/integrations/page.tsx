'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { AlertTriangle, ArrowRight, Ban, Cable, CalendarClock, Layers, Plus, RefreshCw, ShieldOff } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { CatalogGrid } from '@/components/integrations/catalog-grid';
import { ConnectDialog } from '@/components/integrations/connect-dialog';
import { AUTH, IntegrationStatusBadge, KIND, STATUS_LABEL, SystemMark } from '@/components/integrations/integration-meta';
import { RevokeDialog } from '@/components/integrations/revoke-dialog';
import { PageLayout } from '@/components/page-layout';
import { toastBulk } from '@/components/shared/bulk';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { selectColumn } from '@/components/shared/select-column';
import { ExpiryText } from '@/components/tools/module-meta';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useBulkCheckIntegrations, useConnectFlow, useIntegrations, useRevokeImpact, useRevokeIntegrations } from '@/hooks/integration-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { useTabParam } from '@/hooks/use-tab-param';
import { plural, relativeTime } from '@/lib/format';
import type { AuthMethod, CatalogSystem, Integration, IntegrationFilters, IntegrationKind, IntegrationStatus, IntegrationView } from '@/lib/types/integrations';

type Row = Integration & { onOpen: (i: Integration) => void };

const TABS = ['connected', 'catalog'] as const;
const VIEW_EMPTY: Record<IntegrationView, string> = {
  all: 'Connect a system once; sources, tool modules and mailboxes then pick the connection.',
  attention: 'Every connection is signing in and answering.',
  expiring: 'No consent or credential ends in the next 30 days.',
  revoked: 'No connection has been revoked.',
};

function usedByText(i: Integration) {
  const parts = [i.usedBy.sources && plural(i.usedBy.sources, 'source'), i.usedBy.modules && plural(i.usedBy.modules, 'tool module'), i.usedBy.mailboxes && plural(i.usedBy.mailboxes, 'mailbox', 'mailboxes')].filter(Boolean);
  return parts.length ? parts.join(' · ') : null;
}

function columns(onRecheck: (i: Integration) => void, onRevoke: (i: Integration) => void): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((i) => i.name),
    {
      // Holds every searched field so the table's own filter keeps the rows the server matched.
      id: 'name',
      accessorFn: (i) => `${i.name} ${i.instanceUrl} ${i.ownerTeam} ${KIND[i.kind].label}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="System" />,
      cell: ({ row }) => (
        <div className="flex w-64 max-w-64 items-center gap-3" title={`${row.original.name} · ${row.original.instanceUrl}`}>
          <SystemMark kind={row.original.kind} />
          <div className="min-w-0">
            <div className="truncate font-medium">{row.original.name}</div>
            <div className="truncate text-xs text-muted-foreground">
              {KIND[row.original.kind].label} · <span className="font-mono">{row.original.instanceUrl.replace(/^https?:\/\//, '')}</span>
            </div>
          </div>
        </div>
      ),
      enableHiding: false,
    },
    { accessorKey: 'kind', header: ({ column }) => <DataTableColumnHeader column={column} title="Kind" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap">{KIND[row.original.kind].label}</span>, filterFn: facetFilterFn },
    { accessorKey: 'authMethod', header: ({ column }) => <DataTableColumnHeader column={column} title="Sign-in" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap">{AUTH[row.original.authMethod].label}</span>, filterFn: facetFilterFn },
    { id: 'scopes', accessorFn: (i) => i.scopeSummary, header: ({ column }) => <DataTableColumnHeader column={column} title="Scopes" />, cell: ({ row }) => <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">{row.original.scopeSummary}</span> },
    { accessorKey: 'ownerTeam', header: ({ column }) => <DataTableColumnHeader column={column} title="Owner" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap">{row.original.ownerTeam}</span>, filterFn: facetFilterFn },
    {
      accessorKey: 'status',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
      cell: ({ row }) => (
        <div className="flex w-44 flex-col items-start gap-0.5">
          <IntegrationStatusBadge status={row.original.status} />
          {row.original.lastError && row.original.status !== 'healthy' && row.original.status !== 'expiring' && (
            <span className="block w-full truncate text-xs text-muted-foreground" title={row.original.lastError}>
              {row.original.lastError}
            </span>
          )}
        </div>
      ),
      filterFn: facetFilterFn,
    },
    { id: 'expiresAt', accessorFn: (i) => i.expiresAt ?? '', header: ({ column }) => <DataTableColumnHeader column={column} title="Expiry" />, cell: ({ row }) => (row.original.status === 'revoked' ? <span className="text-xs text-muted-foreground">Revoked</span> : <ExpiryText at={row.original.expiresAt} />) },
    {
      id: 'usedBy',
      accessorFn: (i) => i.usedBy.sources + i.usedBy.modules + i.usedBy.mailboxes,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Used by" />,
      cell: ({ row }) => {
        const t = usedByText(row.original);
        return t ? <span className="block max-w-48 truncate text-sm" title={t}>{t}</span> : <span className="text-xs text-muted-foreground">Nothing yet</span>;
      },
    },
    { accessorKey: 'lastCheckedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last checked" />, cell: ({ row }) => <span className="text-xs whitespace-nowrap text-muted-foreground">{relativeTime(row.original.lastCheckedAt)}</span> },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Open', icon: ArrowRight, onClick: (r) => r.original.onOpen(r.original) },
              { label: 'Re-check health', icon: RefreshCw, onClick: (r) => onRecheck(r.original) },
              { label: 'Revoke', icon: Ban, variant: 'destructive', onClick: (r) => onRevoke(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function IntegrationsPage() {
  const router = useRouter();
  const [tab, setTab] = useTabParam(TABS, 'connected');
  const [view, setView] = React.useState<IntegrationView>('all');
  const list = useListParams<IntegrationFilters>('name');
  const query = useIntegrations({ ...list.params, view });
  const [connectFor, setConnectFor] = React.useState<{ system?: CatalogSystem } | null>(null);
  const flow = useConnectFlow(tab === 'catalog' || !!connectFor);
  const bulkCheck = useBulkCheckIntegrations();
  const revoke = useRevokeIntegrations();
  const [revoking, setRevoking] = React.useState<Integration[] | null>(null);
  const shownRevoking = useSticky(revoking);
  const impact = useRevokeImpact((revoking ?? []).map((i) => i.id));
  const [resetKey, setResetKey] = React.useState(0);
  const [filterResetKey, setFilterResetKey] = React.useState(0);

  const rows0 = query.data?.data ?? [];
  const counts = query.data?.viewCounts;
  const facets = query.data?.facets ?? {};
  const recheck = React.useCallback(
    async (items: Integration[]) => {
      try {
        const res = await bulkCheck.mutateAsync(items.map((i) => i.id));
        toastBulk(res, 'Re-checked', 'connection', (rid) => items.find((i) => i.id === rid)?.name ?? rid);
        setResetKey((k) => k + 1);
      } catch (e) {
        toast.error('Couldn’t re-check', { description: (e as Error).message });
      }
    },
    [bulkCheck],
  );
  const cols = React.useMemo(() => columns((i) => recheck([i]), (i) => setRevoking([i])), [recheck]);
  const rows: Row[] = React.useMemo(() => rows0.map((i) => ({ ...i, onOpen: (x: Integration) => router.push(`/integrations/${x.id}`) })), [rows0, router]);
  const optionsOf = <K extends string>(key: string, label: (k: K) => string) => Object.keys(facets[key] ?? {}).map((k) => ({ label: label(k as K), value: k, count: facets[key]?.[k] ?? 0 }));

  return (
    <PageLayout
      icon={Cable}
      title="Integrations"
      description="Every bank system the platform signs in to: credentials, scopes, owners, expiry and what depends on each"
      actions={
        <Button onClick={() => setConnectFor({})}>
          <Plus className="size-4" /> Connect a system
        </Button>
      }
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as (typeof TABS)[number])}>
          <TabsList>
            <TabsTrigger value="connected">
              Connected{counts && <span className="ml-1 text-muted-foreground tabular-nums">{counts.all}</span>}
            </TabsTrigger>
            <TabsTrigger value="catalog">Catalog</TabsTrigger>
          </TabsList>
        </Tabs>
      }
    >
      {tab === 'catalog' ? (
        !flow.catalog.length && flow.catalogState.isPending ? (
          <PageSkeleton statCards={0} tableRows={6} showToolbar={false} />
        ) : flow.catalogState.isError ? (
          <QueryError what="the catalog" onRetry={() => flow.catalogState.refetch()} retrying={flow.catalogState.isFetching} error={flow.catalogState.error} />
        ) : flow.catalog.length ? (
          <CatalogGrid items={flow.catalog} onConnect={(system) => setConnectFor({ system })} />
        ) : (
          <ListEmpty icon={Layers} noun="catalog systems" filtered={false} description="The catalog is empty. Ask the platform team to publish the systems teams may connect." />
        )
      ) : query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="integrations" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
      ) : (
        <div className="flex flex-col gap-4">
          <SavedViewTabs
            ariaLabel="Integration views"
            presets={[
              { id: 'all', label: `All · ${counts?.all ?? 0}`, icon: Cable },
              { id: 'attention', label: `Needs attention · ${counts?.attention ?? 0}`, icon: AlertTriangle },
              { id: 'expiring', label: `Expiring in 30 days · ${counts?.expiring ?? 0}`, icon: CalendarClock },
              { id: 'revoked', label: `Revoked · ${counts?.revoked ?? 0}`, icon: ShieldOff },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(vid) => {
              setView(vid as IntegrationView);
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
            initialColumnVisibility={{ kind: false, lastCheckedAt: false }}
            searchColumn="name"
            searchPlaceholder="Search systems, URLs or owners…"
            filters={[
              { column: 'kind', title: 'Kind', options: optionsOf<IntegrationKind>('kind', (k) => KIND[k]?.label ?? k) },
              { column: 'authMethod', title: 'Sign-in', options: optionsOf<AuthMethod>('authMethod', (k) => AUTH[k]?.label ?? k) },
              { column: 'status', title: 'Status', options: optionsOf<IntegrationStatus>('status', (k) => STATUS_LABEL[k] ?? k) },
              { column: 'ownerTeam', title: 'Owner', options: optionsOf<string>('ownerTeam', (k) => k) },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            selectionResetKey={resetKey}
            filterResetKey={filterResetKey}
            bulkActions={[
              { label: 'Re-check health', icon: RefreshCw, onClick: (rs) => recheck(rs) },
              { label: 'Revoke', icon: Ban, variant: 'destructive', onClick: (rs) => setRevoking(rs) },
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
                icon={Cable}
                noun={view === 'all' ? 'integrations' : 'integrations in this view'}
                filtered={list.isFiltered}
                onClear={() => setFilterResetKey((k) => k + 1)}
                description={VIEW_EMPTY[view]}
                createLabel={view === 'all' ? 'Connect a system' : undefined}
                onCreate={view === 'all' ? () => setConnectFor({}) : undefined}
              />
            }
          />
        </div>
      )}

      <ConnectDialog
        open={!!connectFor}
        onOpenChange={(o) => !o && setConnectFor(null)}
        catalog={flow.catalog}
        initialSystemId={connectFor?.system?.id}
        teams={flow.teams}
        defaultTeam={flow.defaultTeam}
        currentUser={flow.currentUser}
        connecting={flow.connecting}
        onConnect={async (input) => {
          const i = await flow.connect(input);
          toast.success(`Connected ${i.name}`, { description: 'Sources, tool modules and mailboxes can now pick it.' });
          setConnectFor(null);
          router.push(`/integrations/${i.id}`);
        }}
      />
      <RevokeDialog
        open={!!revoking}
        onOpenChange={(o) => !o && setRevoking(null)}
        names={(shownRevoking ?? []).map((i) => i.name)}
        impact={impact.data}
        impactLoading={impact.isPending}
        isPending={revoke.isPending}
        onConfirm={async (reason) => {
          try {
            const res = await revoke.mutateAsync({ ids: revoking!.map((i) => i.id), reason });
            toastBulk(res, 'Revoked', 'connection', (rid) => shownRevoking?.find((i) => i.id === rid)?.name ?? rid);
            setRevoking(null);
            setResetKey((k) => k + 1);
          } catch (e) {
            toast.error('Couldn’t revoke', { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
