'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { UserCog, UserPlus, Users, UserX } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { InviteDialog } from '@/components/settings/invite-dialog';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useInviteMembers, useMembers, useRemoveMembers, useSetMemberRole, useSettingsLookups } from '@/hooks/settings-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { useTeam } from '@/hooks/use-team';
import { initials, relativeTime } from '@/lib/format';
import type { Member, MemberFilters, MemberRole } from '@/lib/types/settings';

function columns(roleLabel: (r: MemberRole) => string, showTeam: boolean, onRole: (m: Member) => void, onRemove: (m: Member) => void): ColumnDef<Member>[] {
  return [
    selectColumn<Member>((m) => m.name),
    {
      id: 'name',
      accessorFn: (m) => `${m.name} ${m.email}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Member" />,
      cell: ({ row }) => (
        <div className="flex min-w-52 items-center gap-3">
          <span aria-hidden="true" className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
            {initials(row.original.name)}
          </span>
          <div className="min-w-0">
            <div className="truncate font-medium">{row.original.name}</div>
            <div className="truncate text-xs text-muted-foreground">{row.original.email}</div>
          </div>
        </div>
      ),
      enableHiding: false,
    },
    ...(showTeam ? [{ accessorKey: 'teamId', header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.team}</span>, filterFn: facetFilterFn } as ColumnDef<Member>] : []),
    { accessorKey: 'role', header: ({ column }) => <DataTableColumnHeader column={column} title="Role" />, cell: ({ row }) => <Badge variant={row.original.role === 'admin' ? 'secondary' : 'outline'} className="font-normal">{roleLabel(row.original.role)}</Badge>, filterFn: facetFilterFn },
    {
      accessorKey: 'status',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
      cell: ({ row }) => (row.original.status === 'invited' ? <span className="text-xs text-amber-700 dark:text-amber-400">Invited {relativeTime(row.original.invitedAt)}</span> : <span className="text-xs text-muted-foreground">Active</span>),
      filterFn: facetFilterFn,
    },
    { accessorKey: 'lastActiveAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last active" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.lastActiveAt ? relativeTime(row.original.lastActiveAt) : '—'}</span> },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Change role', icon: UserCog, onClick: (r) => onRole(r.original) },
              { label: 'Remove', icon: UserX, variant: 'destructive', onClick: (r) => onRemove(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'invited', label: 'Invited' },
];

export default function MembersPage() {
  const { team, teams } = useTeam();
  const showTeam = team?.scope === 'all';
  const list = useListParams<MemberFilters>('name', 20);
  const query = useMembers(list.params);
  const lookups = useSettingsLookups();
  const invite = useInviteMembers();
  const setRole = useSetMemberRole();
  const remove = useRemoveMembers();
  const [inviteOpen, setInviteOpen] = React.useState(false);
  const [action, setAction] = React.useState<{ kind: 'role' | 'remove'; rows: Member[] } | null>(null);
  const shown = useSticky(action);
  const [resetKey, setResetKey] = React.useState(0);

  const roles = lookups.data?.roles ?? [];
  const roleLabel = React.useCallback((r: MemberRole) => roles.find((x) => x.value === r)?.label ?? r, [roles]);
  const cols = React.useMemo(() => columns(roleLabel, showTeam, (m) => setAction({ kind: 'role', rows: [m] }), (m) => setAction({ kind: 'remove', rows: [m] })), [roleLabel, showTeam]);
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, opts: { label: string; value: string }[]) => opts.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const nameOf = (id: string) => shown?.rows.find((m) => m.id === id)?.name ?? id;

  return (
    <SettingsPageLayout
      section="Members and roles"
      description={showTeam ? 'Everyone in every team. Roles apply within the member’s team.' : `Everyone in ${team?.name ?? 'this team'} and what they can do.`}
      actions={
        <Button onClick={() => setInviteOpen(true)}>
          <UserPlus className="size-4" /> Invite
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="members" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={query.data?.data ?? []}
          getRowId={(m) => m.id}
          searchColumn="name"
          searchPlaceholder="Search names or emails…"
          filters={[
            { column: 'role', title: 'Role', options: withCounts('role', roles.map((r) => ({ value: r.value, label: r.label }))) },
            { column: 'status', title: 'Status', options: withCounts('status', STATUS_OPTIONS) },
            ...(showTeam ? [{ column: 'teamId', title: 'Team', options: withCounts('teamId', teams.map((t) => ({ value: t.id, label: t.name }))) }] : []),
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={[
            { label: 'Change role', icon: UserCog, variant: 'outline', onClick: (rows) => setAction({ kind: 'role', rows }) },
            { label: 'Remove', icon: UserX, variant: 'destructive', onClick: (rows) => setAction({ kind: 'remove', rows }) },
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
          emptyState={<ListEmpty icon={Users} noun="members" filtered={list.isFiltered} createLabel="Invite" onCreate={() => setInviteOpen(true)} description="Invite the people who build, approve and watch this team’s workflows." />}
        />
      )}

      <InviteDialog
        open={inviteOpen}
        onOpenChange={setInviteOpen}
        teamName={team?.name ?? 'team'}
        teams={showTeam ? teams.map((t) => ({ id: t.id, name: t.name })) : undefined}
        defaultTeamId={team?.id}
        roles={roles}
        isPending={invite.isPending}
        onSubmit={async (input) => toastBulk(await invite.mutateAsync(input), 'Invited', 'person')}
      />
      <BulkFieldDialog
        open={action?.kind === 'role'}
        onOpenChange={(o) => !o && setAction(null)}
        title={shown?.rows.length === 1 ? `Change role for ${shown.rows[0].name}` : `Change role for ${shown?.rows.length ?? 0} members`}
        description="Takes effect on their next page load. A team always keeps at least one admin."
        fieldLabel="Role"
        options={roles.map((r) => r.label)}
        names={(shown?.rows ?? []).map((m) => m.name)}
        confirmLabel="Change role"
        isPending={setRole.isPending}
        onConfirm={async (label) => {
          const role = roles.find((r) => r.label === label)!.value;
          toastBulk(await setRole.mutateAsync({ ids: action!.rows.map((m) => m.id), role }), `Changed role to ${label} for`, 'member', nameOf);
          setResetKey((k) => k + 1);
        }}
      />
      <DeleteDialog
        open={action?.kind === 'remove'}
        onOpenChange={(o) => !o && setAction(null)}
        entityType="member"
        verb="Remove"
        entityName={shown?.rows.length === 1 ? shown.rows[0].name : undefined}
        count={shown && shown.rows.length > 1 ? shown.rows.length : undefined}
        description="They lose access to this team at once. Reviews assigned to them return to the queue. You can’t remove yourself or a team’s last admin."
        confirmText="Remove"
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            toastBulk(await remove.mutateAsync(action!.rows.map((m) => m.id)), 'Removed', 'member', nameOf);
            setAction(null);
            setResetKey((k) => k + 1);
          } catch (e) {
            toast.error('Couldn’t remove members', { description: (e as Error).message });
          }
        }}
      />
    </SettingsPageLayout>
  );
}
