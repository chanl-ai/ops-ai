'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, ShieldCheck } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { idColumn } from '@/components/shared/id-column';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { countLabel, SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { Badge } from '@/components/ui/badge';
import { useToolGrants } from '@/hooks/tool-module-queries';
import { useListParams } from '@/hooks/use-list-params';
import { relativeTime } from '@/lib/format';
import type { GrantView, ToolGrant } from '@/lib/types/tool-modules';

const VIEWS: { id: GrantView; label: string }[] = [
  { id: 'active', label: 'Active' },
  { id: 'expiring', label: 'Expiring' },
  { id: 'requested', label: 'Requested' },
  { id: 'expired', label: 'Expired' },
  { id: 'ended', label: 'Ended' },
  { id: 'all', label: 'All' },
];
const STATUS: Record<ToolGrant['status'], string> = { requested: 'Requested', approved: 'Active', rejected: 'Refused', expired: 'Expired', revoked: 'Ended' };

type Row = ToolGrant & { href: string; onRowClick: () => void; rowTestId: string };

const COLUMNS: ColumnDef<Row>[] = [
  idColumn<Row>((r) => r.id),
  {
    accessorKey: 'workflowName',
    header: 'Workflow',
    cell: ({ row }) => (
      <span className="min-w-0">
        <span className="block truncate font-medium">{row.original.workflowName}</span>
        <span className="block truncate text-xs text-muted-foreground">{row.original.moduleName}</span>
      </span>
    ),
    enableHiding: false,
  },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => <Badge variant={row.original.status === 'approved' ? 'secondary' : 'outline'}>{STATUS[row.original.status]}</Badge> },
  { id: 'expires', header: 'Ends', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.expiresAt ? relativeTime(row.original.expiresAt) : 'No end'}</span> },
  { id: 'access', header: 'May call', cell: ({ row }) => <span className="text-muted-foreground">{row.original.operations.join(', ') || 'Every operation'}</span> },
  { accessorKey: 'environment', header: 'Environment', cell: ({ row }) => <span className="capitalize">{row.original.environment}</span> },
  { id: 'decided', header: 'Decided by', cell: ({ row }) => <span className="text-muted-foreground">{row.original.decidedBy ?? '—'}</span> },
];

/** Access › Tool access: every workflow's access to the team's tool modules, by view, from tools-service (c-144). */
export default function ToolAccessPage() {
  const router = useRouter();
  const [view, setView] = React.useState<GrantView>('active');
  const list = useListParams<Record<string, never>>('workflowName');
  const q = useToolGrants({ view, search: list.params.search, page: list.params.page, pageSize: list.params.pageSize });
  const counts = q.data?.facets?.view ?? {};
  const rows: Row[] = React.useMemo(
    () => (q.data?.data ?? []).map((g) => ({ ...g, href: `/tools/${encodeURIComponent(g.moduleId)}`, onRowClick: () => router.push(`/tools/${encodeURIComponent(g.moduleId)}`), rowTestId: `grant-row-${g.id}` })),
    [q.data, router],
  );
  return (
    <PageLayout icon={ShieldCheck} title="Tool access" switcher description="Which workflows may call which tool modules, and until when">
      {q.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : q.isError && !q.data ? (
        <QueryError what="tool access" error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          <SavedViewTabs
            ariaLabel="Tool access views"
            presets={VIEWS.map((v) => ({ id: v.id, label: countLabel(v.label, counts[v.id]) }))}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as GrantView);
              list.reset();
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />
          <DataTableWithViews
            columns={COLUMNS}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="workflowName"
            searchPlaceholder="Search workflows or modules…"
            hideViewSwitcher
            onColumnFiltersChange={list.onColumnFiltersChange}
            serverPagination={{ enabled: true, total: q.data.pagination.total, page: list.pagination.page, pageSize: list.pagination.pageSize, totalPages: q.data.pagination.totalPages, onPaginationChange: list.setPagination, isLoading: q.isFetching && q.isPlaceholderData }}
            emptyState={<ListEmpty icon={KeyRound} noun="tool access" filtered={list.isFiltered} description="A workflow asks for a tool module’s operations on the module’s page; the owning team decides." />}
          />
        </div>
      )}
    </PageLayout>
  );
}
