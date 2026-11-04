'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, Wrench } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { serverPagination } from '@/components/shared/server-pagination';
import { AccessBadge } from '@/components/status-badges';
import { ToolSetActions } from '@/components/tools/tool-set-actions';
import { ToolsTabs } from '@/components/tools/tools-tabs';
import { toolHref, UsedByCell } from '@/components/tools/used-by';
import { Badge } from '@/components/ui/badge';
import { useToolDirectory } from '@/hooks/queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import type { ToolKind, ToolRow, ToolRowFilters, ToolStatus } from '@/lib/types/tool-directory';

const KIND: Record<ToolKind, string> = { app: 'App tool', custom: 'Custom tool', workflow: 'Workflow', agent: 'Agent' };
const STATUS: Record<ToolStatus, { label: string; className: string }> = {
  ready: { label: 'Ready', className: 'border-success/40 bg-success/10 text-success-text' },
  needs_approval: { label: 'Needs approval', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  app_not_connected: { label: 'App not connected', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  needs_your_sign_in: { label: 'Needs your sign-in', className: 'border-warning/40 bg-warning/10 text-warning-text' },
};

type Row = ToolRow & { onRowClick: (t: ToolRow) => void; href?: string };

const columns: ColumnDef<Row>[] = [
  {
    // Holds every searched field so the table's own filter keeps the rows the server matched.
    id: 'name',
    accessorFn: (t) => `${t.title ?? ''} ${t.name} ${t.app?.name ?? ''}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Tool" />,
    cell: ({ row }) => (
      <div className="flex max-w-72 min-w-44 flex-col" data-testid={`tool-row-${row.original.name}`}>
        <span className="truncate font-medium">{row.original.title ?? row.original.name}</span>
        {row.original.title && row.original.title !== row.original.name && <code className="truncate font-mono text-xs text-muted-foreground">{row.original.name}</code>}
      </div>
    ),
    enableHiding: false,
  },
  {
    id: 'app',
    accessorFn: (t) => t.app?.name ?? '',
    // Filtered by the app's id, as the server filters and its facet counts; the column shows the name.
    filterFn: (row, _id, value: string[]) => !value?.length || value.includes(row.original.app?.id ?? ''),
    header: ({ column }) => <DataTableColumnHeader column={column} title="App" />,
    cell: ({ row }) =>
      row.original.app ? (
        <StopRowClick align="start">
          <Link href={`/integrations/apps/${encodeURIComponent(row.original.app.id)}`} className="text-sm underline-offset-4 hover:underline">
            {row.original.app.name}
          </Link>
        </StopRowClick>
      ) : (
        <span className="text-xs text-muted-foreground">Built in</span>
      ),
  },
  { accessorKey: 'kind', header: ({ column }) => <DataTableColumnHeader column={column} title="Kind" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap">{KIND[row.original.kind]}</span>, filterFn: facetFilterFn },
  { accessorKey: 'access', header: ({ column }) => <DataTableColumnHeader column={column} title="Access" />, cell: ({ row }) => <AccessBadge access={row.original.access} /> },
  {
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
    cell: ({ row }) => (
      <Badge variant="outline" className={STATUS[row.original.status].className}>
        {STATUS[row.original.status].label}
      </Badge>
    ),
    filterFn: facetFilterFn,
  },
  {
    id: 'usedBy',
    accessorFn: (t) => t.usedBy.agents.length + t.usedBy.workflows.length,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Used by" />,
    cell: ({ row }) => (
      <StopRowClick align="start">
        <UsedByCell usedBy={row.original.usedBy} testId={`used-by-${row.original.name}`} />
      </StopRowClick>
    ),
  },
  {
    id: 'actions',
    meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
    cell: ({ row }) =>
      row.original.href ? (
        <StopRowClick>
          <DataTableRowActions row={row} actions={[{ label: 'Open', icon: ArrowRight, onClick: (r) => r.original.onRowClick(r.original) }]} />
        </StopRowClick>
      ) : null,
    enableHiding: false,
  },
];

/**
 * Every tool the team can use, one row each: its app, kind, access, status and who uses it, read joined from the API.
 * The tabs filter by kind (`?kind=app`, `?kind=custom`); a new tab starts its search and filters fresh.
 */
export default function ToolsPage() {
  const kind = useSearchParams().get('kind');
  return <ToolsList key={kind ?? 'all'} kind={kind === 'app' || kind === 'custom' ? kind : null} />;
}

function ToolsList({ kind }: { kind: ToolKind | null }) {
  const router = useRouter();
  const list = useListParams<ToolRowFilters>('name');
  // The tab's kind is the URL's, kept beside the table's own filters, which never hold it.
  const query = useToolDirectory({ ...list.params, filters: { ...list.params.filters, kind: kind ? [kind] : undefined } });
  const [filterResetKey, setFilterResetKey] = React.useState(0);
  const tools = query.data?.data ?? [];
  const facets = query.data?.facets ?? {};
  const rows: Row[] = React.useMemo(
    () =>
      tools.map((t) => {
        const href = toolHref(t) ?? undefined;
        return { ...t, href, onRowClick: () => href && router.push(href) };
      }),
    [tools, router],
  );
  const withCounts = <K extends string>(column: string, labels: Record<K, string>) =>
    (Object.keys(labels) as K[]).map((value) => ({ label: labels[value], value, count: facets[column]?.[value] ?? 0 }));
  // The apps the facet counts, each by the name the API sends beside it.
  const appNames = query.data?.appNames ?? {};
  return (
    <PageLayout
      switcher
      icon={Wrench}
      title="Tools"
      description="Every tool your team can use, the app it calls and who uses it"
      actions={
        <div className="flex items-center gap-2">
          <ToolSetActions />
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <ToolsTabs />
        {query.isPending ? (
          <PageSkeleton statCards={0} tableRows={8} />
        ) : query.isError && !query.data ? (
          <QueryError what="the tools" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />
        ) : (
          <DataTableWithViews
            columns={columns}
            data={rows}
            getRowId={(r) => r.id}
            // Who uses each tool is the column the page exists for; it shows whatever else the width leaves out.
            initialColumnVisibility={{ usedBy: true }}
            searchColumn="name"
            searchPlaceholder="Search tools or apps…"
            filters={[
              { column: 'app', title: 'App', options: withCounts('app', appNames) },
              { column: 'status', title: 'Status', options: withCounts('status', Object.fromEntries(Object.entries(STATUS).map(([k, v]) => [k, v.label])) as Record<ToolStatus, string>) },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            filterResetKey={filterResetKey}
            serverPagination={serverPagination(list, query)}
            emptyState={
              <ListEmpty
                icon={Wrench}
                noun="tools"
                filtered={list.isFiltered}
                onClear={() => setFilterResetKey((k) => k + 1)}
                description="Connect an app to get its tools, or build your own under Custom tools."
              />
            }
          />
        )}
      </div>
    </PageLayout>
  );
}
