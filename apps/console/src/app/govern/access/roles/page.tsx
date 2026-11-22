'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Plus, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { RoleDialog } from '@/components/access/role-dialog';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { serverPagination } from '@/components/shared/server-pagination';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useCreateRole, useManagesRoles, useRoles } from '@/hooks/me-queries';
import { useListParams } from '@/hooks/use-list-params';
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
        <div className="text-xs text-muted-foreground break-words whitespace-normal">{row.original.description}</div>
      </div>
    ),
    enableHiding: false,
  },
  { id: 'kind', accessorFn: (r) => (r.builtin ? 'Built in' : 'Custom'), header: 'Kind', meta: { kind: 'status' }, cell: ({ row }) => <Badge variant="outline">{row.original.builtin ? 'Built in' : 'Custom'}</Badge> },
  { accessorKey: 'permissionCount', header: ({ column }) => <DataTableColumnHeader column={column} title="Permissions" />, meta: { kind: 'number' } },
  { accessorKey: 'assignmentCount', header: ({ column }) => <DataTableColumnHeader column={column} title="People" />, meta: { kind: 'number' } },
];

/** The table's columns the server sorts by, each with its `sortBy` value. */
const SORT_COLUMNS = { name: 'name', assignmentCount: 'assignmentCount' };

/**
 * Access › Roles: every role of the workspace, what it is for and how many hold it; a row opens its grid. A workspace
 * admin creates a custom role here, empty or as a copy of another.
 */
export default function RolesPage() {
  const router = useRouter();
  const list = useListParams('name', undefined, undefined, SORT_COLUMNS);
  const roles = useRoles(list.params);
  const manages = useManagesRoles();
  const create = useCreateRole();
  const [creating, setCreating] = React.useState(false);
  const rows = React.useMemo(() => (roles.data?.data ?? []).map((r) => ({ ...r, onRowClick: () => router.push(`/govern/access/roles/${encodeURIComponent(r.id)}`), rowTestId: `role-row-${r.id}` })), [roles.data, router]);
  return (
    <PageLayout
      icon={ShieldCheck}
      title="Roles"
      switcher
      description="What each role allows; a workspace admin changes any role but Admin and makes the workspace's own"
      actions={
        manages ? (
          <Button size="sm" onClick={() => setCreating(true)} data-testid="role-create">
            <Plus className="size-4" />
            Create role
          </Button>
        ) : undefined
      }
    >
      {roles.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : roles.isError && !roles.data ? (
        <QueryError what="roles" error={roles.error} onRetry={() => roles.refetch()} retrying={roles.isFetching} />
      ) : (
        <DataTableWithViews
          columns={COLUMNS}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="name"
          searchPlaceholder="Search roles…"
          onColumnFiltersChange={list.onColumnFiltersChange}
          serverPagination={serverPagination(list, roles)}
          serverSorting={list.serverSort}
          hideViewSwitcher
          emptyState={<ListEmpty icon={ShieldCheck} noun="roles" filtered={list.isFiltered} description="Roles come with the workspace; none were found." />}
        />
      )}
      <RoleDialog
        open={creating}
        onOpenChange={setCreating}
        pending={create.isPending}
        onSubmit={(input) =>
          create.mutateAsync(input).then((made) => {
            toast.success(`Created ${made.name}`, (made.leftOut ?? []).length ? { description: `Left out ${(made.leftOut ?? []).length} secrets, egress and Security-team permissions: only a built-in role holds them.` } : undefined);
            router.push(`/govern/access/roles/${encodeURIComponent(made.id)}`);
          })
        }
      />
    </PageLayout>
  );
}
