'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { ShieldCheck } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { useRoles } from '@/hooks/me-queries';
import type { RoleSummary } from '@/lib/types/settings';

type Row = RoleSummary & { onRowClick: () => void; rowTestId: string };

const COLUMNS: ColumnDef<Row>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Role" />,
    meta: { kind: 'name' },
    cell: ({ row }) => (
      <div className="min-w-0">
        <div className="truncate font-medium">{row.original.name}</div>
        <div className="truncate text-xs text-muted-foreground">{row.original.description}</div>
      </div>
    ),
    enableHiding: false,
  },
  { id: 'kind', accessorFn: (r) => (r.builtin ? 'Built in' : 'Custom'), header: 'Kind', meta: { kind: 'status' }, cell: ({ row }) => <Badge variant="outline">{row.original.builtin ? 'Built in' : 'Custom'}</Badge> },
  { accessorKey: 'permissionCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Permissions" />, meta: { kind: 'number' } },
  { accessorKey: 'assignmentCount', header: ({ column }) => <DataTableColumnHeader column={column} title="People" />, meta: { kind: 'number' } },
];

/** Access › Roles (c-150): every role of the workspace, what it is for and how many hold it; a row opens its grid. */
export default function RolesPage() {
  const router = useRouter();
  const roles = useRoles();
  const rows = React.useMemo(() => (roles.data ?? []).map((r) => ({ ...r, onRowClick: () => router.push(`/access/roles/${encodeURIComponent(r.id)}`), rowTestId: `role-row-${r.id}` })), [roles.data, router]);
  return (
    <PageLayout icon={ShieldCheck} title="Roles" switcher description="What each role allows; built-in roles are read-only">
      {roles.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : roles.isError ? (
        <QueryError what="roles" error={roles.error} onRetry={() => roles.refetch()} retrying={roles.isFetching} />
      ) : (
        <DataTableWithViews
          columns={COLUMNS}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="name"
          searchPlaceholder="Search roles…"
          hideViewSwitcher
          emptyState={<ListEmpty icon={ShieldCheck} noun="roles" filtered={false} description="Roles come with the workspace; none were found." />}
        />
      )}
    </PageLayout>
  );
}
