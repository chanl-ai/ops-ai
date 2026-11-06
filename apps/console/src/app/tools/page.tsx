'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, Wrench } from 'lucide-react';

import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { serverPagination } from '@/components/shared/server-pagination';
import { ToolSetActions } from '@/components/tools/tool-set-actions';
import { ToolsTabs } from '@/components/tools/tools-tabs';
import { toolColumns, TOOL_STATUS } from '@/components/tools/tools-table';
import { toolHref } from '@/components/tools/used-by';
import { useToolDirectory } from '@/hooks/queries';
import { useListParams } from '@/hooks/use-list-params';
import type { ToolKind, ToolRow, ToolRowFilters, ToolStatus } from '@/lib/types/tool-directory';

type Row = ToolRow & { onRowClick: (t: ToolRow) => void; href?: string };

const columns: ColumnDef<Row>[] = [
  ...toolColumns<Row>({ app: true, kind: true, status: true }),
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
              { column: 'status', title: 'Status', options: withCounts('status', Object.fromEntries(Object.entries(TOOL_STATUS).map(([k, v]) => [k, v.label])) as Record<ToolStatus, string>) },
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
