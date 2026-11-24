'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Layers } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { serverPagination } from '@/components/shared/server-pagination';
import { workflowHeader } from '@/components/workflows/definition-editor/editor-shell';
import { useWorkflowBatches } from '@/hooks/batch-queries';
import { useDefinition } from '@/hooks/engine-queries';
import { useListParams } from '@/hooks/use-list-params';
import { shortDate } from '@/lib/format';
import type { BatchLine } from '@/lib/types/batches';

const SORT_COLUMNS = { createdAt: 'createdAt' };

/** What a line's rows have come to, in the batch page's words; counts the API made. */
function counts(b: BatchLine): string {
  const parts = [
    `${b.finished} read`,
    b.waiting ? `${b.waiting} waiting for a person` : '',
    b.failed ? `${b.failed} failed` : '',
    b.removed ? `${b.removed} removed` : '',
    b.running || b.pending ? `${b.running + b.pending} to go` : '',
  ];
  return parts.filter(Boolean).join(' · ');
}

/**
 * The Batches tab: every batch of the workflow, newest first, a spreadsheet's rows and each check of a watched folder
 * alike. Each line opens the batch's page. Anyone who may view the workflow reads it.
 */
export default function WorkflowBatchesPage() {
  const { id } = useParams<{ id: string }>();
  const definition = useDefinition(id);
  const router = useRouter();
  const list = useListParams<Record<string, string[] | undefined>>(undefined, undefined, undefined, SORT_COLUMNS);
  const page = useWorkflowBatches(id, list.params);
  const columns = React.useMemo<ColumnDef<BatchLine>[]>(
    () => [
      {
        id: 'label',
        header: 'Batch',
        meta: { kind: 'name' },
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col">
            <span className="truncate">{row.original.label}</span>
            <span className="text-xs text-muted-foreground">{row.original.origin === 'check' ? 'Check of a watched folder' : 'Spreadsheet'}</span>
          </div>
        ),
      },
      {
        id: 'createdAt',
        accessorKey: 'createdAt',
        header: ({ column }) => <DataTableColumnHeader column={column} title="When" />,
        meta: { kind: 'date' },
        cell: ({ row }) => shortDate(row.original.checkedAt ?? row.original.createdAt),
      },
      { id: 'total', header: 'Files or rows', meta: { kind: 'number' }, cell: ({ row }) => row.original.total },
      { id: 'counts', header: 'Where they are', meta: { kind: 'description' }, cell: ({ row }) => <span data-testid="batch-line-counts">{counts(row.original)}</span> },
    ],
    [],
  );
  return (
    <PageLayout {...workflowHeader(id, definition.data)}>
      {page.isPending ? (
        <PageSkeleton statCards={0} tableRows={5} />
      ) : page.isError ? (
        <QueryError what="this workflow's batches" error={page.error} onRetry={() => page.refetch()} retrying={page.isFetching} />
      ) : (
        <DataTableWithViews
          columns={columns}
          data={(page.data?.data ?? []).map((b) => ({ ...b, rowTestId: 'workflow-batch', onRowClick: () => router.push(`/build/runs/batches/${encodeURIComponent(b.id)}`) }))}
          getRowId={(b) => b.id}
          onColumnFiltersChange={list.onColumnFiltersChange}
          serverPagination={serverPagination(list, page)}
          serverSorting={list.serverSort}
          hideViewSwitcher
          emptyState={
            <EmptyState
              icon={Layers}
              title="No batches yet"
              description="A batch starts the workflow once per row of a spreadsheet, or once per new or changed file each time a watched folder is checked."
            />
          }
        />
      )}
    </PageLayout>
  );
}
