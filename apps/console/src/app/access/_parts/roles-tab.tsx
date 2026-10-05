'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { User, Users, UserX } from 'lucide-react';

import { CAPABILITY_LABEL, CapabilityChips } from '@/components/access/access-meta';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { options } from '@/components/logs/log-meta';
import { BulkConfirmDialog, toastBulk } from '@/components/shared/bulk';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { useRemoveRoles, useRoles } from '@/hooks/governance-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { plural, relativeTime } from '@/lib/format';
import type { RoleAssignment, RoleFilters } from '@/lib/types/governance';
import type { Team } from '@/lib/types/team';

function columns(showTeam: boolean): ColumnDef<RoleAssignment>[] {
  return [
    selectColumn<RoleAssignment>((r) => r.principal),
    {
      id: 'principal',
      accessorFn: (r) => `${r.principal} ${r.team}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Person or group" />,
      cell: ({ row }) => {
        const Icon = row.original.principalKind === 'group' ? Users : User;
        return (
          <div className="flex min-w-48 items-center gap-2">
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <div>
              <div className="font-medium">{row.original.principal}</div>
              <div className="text-xs text-muted-foreground">{row.original.principalKind === 'group' ? plural(row.original.members, 'member') : 'Person'}</div>
            </div>
          </div>
        );
      },
      enableHiding: false,
    },
    { accessorKey: 'principalKind', header: () => null, cell: () => null, filterFn: facetFilterFn, enableHiding: false },
    ...(showTeam ? [{ accessorKey: 'teamId', header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.team}</span>, filterFn: facetFilterFn } as ColumnDef<RoleAssignment>] : []),
    {
      id: 'capabilities',
      accessorFn: (r) => r.capabilities,
      header: 'Can',
      cell: ({ row }) => <CapabilityChips capabilities={row.original.capabilities} />,
      filterFn: (row, id, value: string[]) => !value?.length || (row.getValue(id) as string[]).some((c) => value.includes(c)),
    },
    {
      accessorKey: 'addedBy',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Added by" />,
      cell: ({ row }) => (
        <div className="min-w-32">
          <div className="text-sm">{row.original.addedBy}</div>
          <div className="text-xs text-muted-foreground">{relativeTime(row.original.addedAt)}</div>
        </div>
      ),
    },
  ];
}

/** Who may author, approve and publish workflows, per team. The Platform team sees and edits every team. */
export function RolesTab({ team, teams }: { team?: Team; teams: Team[] }) {
  const showTeam = team?.scope === 'all';
  const list = useListParams<RoleFilters>('principal');
  const query = useRoles(list.params);
  const remove = useRemoveRoles();
  const [removing, setRemoving] = React.useState<RoleAssignment[] | null>(null);
  const shown = useSticky(removing);
  const [resetKey, setResetKey] = React.useState(0);
  const cols = React.useMemo(() => columns(showTeam), [showTeam]);
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, opts: { label: string; value: string }[]) => opts.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));

  if (query.isPending) return <PageSkeleton statCards={0} tableRows={8} />;
  if (query.isError && !query.data) return <QueryError what="roles" onRetry={() => query.refetch()} retrying={query.isFetching} />;

  return (
    <>
      <DataTableWithViews
        columns={cols}
        data={query.data?.data ?? []}
        getRowId={(r) => r.id}
        searchColumn="principal"
        searchPlaceholder="Search people and groups…"
        filters={[
          { column: 'capabilities', title: 'Can', options: withCounts('capabilities', options(CAPABILITY_LABEL)) },
          { column: 'principalKind', title: 'Kind', options: withCounts('principalKind', [{ value: 'group', label: 'Group' }, { value: 'person', label: 'Person' }]) },
          ...(showTeam ? [{ column: 'teamId', title: 'Team', options: withCounts('teamId', teams.map((t) => ({ value: t.id, label: t.name }))) }] : []),
        ]}
        onColumnFiltersChange={list.onColumnFiltersChange}
        selectionResetKey={resetKey}
        bulkActions={[{ label: 'Remove', icon: UserX, variant: 'destructive', onClick: (rows) => setRemoving(rows) }]}
        serverPagination={{
          enabled: true,
          total: query.data?.pagination.total ?? 0,
          page: list.pagination.page,
          pageSize: list.pagination.pageSize,
          totalPages: query.data?.pagination.totalPages,
          onPaginationChange: list.setPagination,
          isLoading: query.isFetching && query.isPlaceholderData,
        }}
        emptyState={<ListEmpty icon={Users} noun="roles" filtered={list.isFiltered} description="Add the people and groups who author, approve and publish this team’s workflows." />}
      />
      <BulkConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Remove ${plural(shown?.length ?? 0, 'role')}`}
        description="They lose author, approve and publish rights in that team at once. Reviews already assigned to them stay assigned. The last publisher in a team is kept."
        names={(shown ?? []).map((r) => `${r.principal} · ${r.team}`)}
        confirmLabel="Remove"
        isPending={remove.isPending}
        onConfirm={async () => {
          const res = await remove.mutateAsync(removing!.map((r) => r.id));
          toastBulk(res, 'Removed', 'role', (id) => removing!.find((r) => r.id === id)?.principal ?? id);
          setResetKey((k) => k + 1);
        }}
      />
    </>
  );
}
