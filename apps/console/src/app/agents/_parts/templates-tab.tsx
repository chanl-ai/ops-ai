'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { LayoutTemplate, Play } from 'lucide-react';

import { CATEGORY_ICON, CATEGORY_ORDER, TemplateCard, TemplatePreview, TemplateStatusBadge } from '@/components/agents/template-meta';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { RiskBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useTemplate, useTemplates } from '@/hooks/template-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, plural, relativeTime } from '@/lib/format';
import type { AgentTemplate, TemplateFilters } from '@/lib/types/templates';

type Row = AgentTemplate & { onRowClick: (t: AgentTemplate) => void };

const RISK = [
  { label: 'Low', value: 'low' },
  { label: 'Medium', value: 'medium' },
  { label: 'High', value: 'high' },
];
const STATUS = [
  { label: 'Published', value: 'published' },
  { label: 'In review', value: 'in_review' },
];

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Template" />,
    cell: ({ row }) => {
      const Icon = CATEGORY_ICON[row.original.category] ?? LayoutTemplate;
      return (
        <div className="flex min-w-64 items-center gap-3">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
            <Icon className="size-4 text-muted-foreground" />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-medium">
              {row.original.name} <TemplateStatusBadge status={row.original.status} />
            </div>
            <div className="max-w-md truncate text-xs text-muted-foreground">{row.original.summary}</div>
          </div>
        </div>
      );
    },
    enableHiding: false,
  },
  { accessorKey: 'category', header: ({ column }) => <DataTableColumnHeader column={column} title="Category" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.category}</span>, filterFn: facetFilterFn },
  { accessorKey: 'riskTier', header: ({ column }) => <DataTableColumnHeader column={column} title="Risk tier" />, cell: ({ row }) => <RiskBadge risk={row.original.riskTier} />, filterFn: facetFilterFn },
  { id: 'expects', header: 'Expects', cell: ({ row }) => <span className="whitespace-nowrap text-xs text-muted-foreground">{plural(row.original.expectedTools.length, 'tool')} · {plural(row.original.expectedKnowledge.length, 'knowledge base')}</span> },
  { accessorKey: 'agentCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Agents" />, cell: ({ row }) => <span className="tabular-nums">{count(row.original.agentCount)}</span> },
  { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => (row.original.status === 'published' ? <span className="text-xs text-muted-foreground">Published</span> : <TemplateStatusBadge status={row.original.status} />), filterFn: facetFilterFn },
  { accessorKey: 'updatedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />, cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground tabular-nums">v{row.original.version} · {relativeTime(row.original.updatedAt)}</span> },
];

/**
 * Templates live as a tab of Agents rather than their own route: people reach for a template while creating an
 * agent, and the tab keeps that choice one click from the list it adds to.
 */
export function TemplatesTab({ onUse }: { onUse: (templateId: string) => void }) {
  const list = useListParams<TemplateFilters>('name');
  const query = useTemplates(list.params);
  const [openId, setOpenId] = React.useState<string | null>(null);
  const detail = useTemplate(openId);
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((t) => ({ ...t, onRowClick: (x: AgentTemplate) => setOpenId(x.id) })), [query.data]);
  const facets = query.data?.facets ?? {};
  const index = rows.findIndex((r) => r.id === openId);
  const current = rows[index];

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={6} />;
  if (query.isError && !query.data) return <QueryError what="templates" onRetry={() => query.refetch()} retrying={query.isFetching} />;

  return (
    <>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        defaultView="grid"
        gridClassName="grid grid-cols-1 gap-3 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3"
        renderGridItem={(t) => <TemplateCard template={t} onSelect={() => setOpenId(t.id)} />}
        searchColumn="name"
        searchPlaceholder="Search templates…"
        filters={[
          { column: 'category', title: 'Category', options: CATEGORY_ORDER.map((c) => ({ label: c, value: c, count: facets.category?.[c] ?? 0 })) },
          { column: 'riskTier', title: 'Risk tier', options: RISK.map((o) => ({ ...o, count: facets.riskTier?.[o.value] ?? 0 })) },
          { column: 'status', title: 'Status', options: STATUS.map((o) => ({ ...o, count: facets.status?.[o.value] ?? 0 })) },
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
        emptyState={<ListEmpty icon={LayoutTemplate} noun="templates" filtered={list.isFiltered} description="Templates are published by the platform team. Save one of your agents as a template to propose one." />}
      />
      <DetailSheet
        open={!!openId}
        onOpenChange={(o) => !o && setOpenId(null)}
        title={current?.name ?? detail.data?.name ?? 'Template'}
        description={current ? `${current.category} · v${current.version}` : undefined}
        scrollKey={openId ?? undefined}
        testId="template-sheet"
        navigation={index >= 0 ? { currentIndex: index, totalCount: rows.length, onPrev: index > 0 ? () => setOpenId(rows[index - 1].id) : undefined, onNext: index < rows.length - 1 ? () => setOpenId(rows[index + 1].id) : undefined } : undefined}
        footerActions={
          <Button size="sm" disabled={detail.data?.status !== 'published'} onClick={() => openId && (onUse(openId), setOpenId(null))} data-testid="use-template">
            <Play className="size-3.5" /> {detail.data && detail.data.status !== 'published' ? 'In review' : 'Use template'}
          </Button>
        }
      >
        {detail.isPending ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-24" />
          </div>
        ) : detail.isError ? (
          <QueryError what="this template" onRetry={() => detail.refetch()} retrying={detail.isFetching} />
        ) : (
          <div className="flex flex-col gap-4">
            <TemplatePreview template={detail.data} />
            <div className="flex flex-col gap-1.5">
              <p className="text-xs font-medium text-muted-foreground">Versions</p>
              <ol className="flex flex-col gap-1 text-xs">
                {detail.data.versions.map((v) => (
                  <li key={v.version} className="flex gap-2">
                    <span className="font-mono font-medium">v{v.version}</span>
                    <span className="min-w-0 flex-1 truncate">{v.note}</span>
                    <span className="text-muted-foreground">{relativeTime(v.publishedAt)}</span>
                  </li>
                ))}
              </ol>
            </div>
            {detail.data.starterTests.length > 0 && (
              <div className="flex flex-col gap-1.5">
                <p className="text-xs font-medium text-muted-foreground">Starter tests</p>
                <ul className="list-disc pl-4 text-xs">
                  {detail.data.starterTests.map((t) => (
                    <li key={t.name}>{t.name}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </DetailSheet>
    </>
  );
}
