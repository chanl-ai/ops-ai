'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { UserCog, Users, UserX } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { MEMBER_ROLES, roleLabel } from '@/components/access/roles';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { InviteDialog } from '@/components/shared/invite-dialog';
import { InviteLinksDialog } from '@/components/shared/invite-links-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { idColumn } from '@/components/shared/id-column';
import { selectColumn } from '@/components/shared/select-column';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { useCan } from '@/hooks/me-queries';
import { useInviteMembers, useInvitesToCurrentTeam, useMembers, useRemoveMembers, useSetMemberRole } from '@/hooks/settings-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { useTeam } from '@/hooks/use-team';
import { initials, relativeTime } from '@/lib/format';
import type { Member, MemberFilters } from '@/lib/types/settings';

/** A member's team role, and any role they hold in every team (access beyond the team role, and where it comes from). */
function MemberRoles({ member }: { member: Member }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <Badge variant={member.role === 'admin' ? 'secondary' : 'outline'} className="font-normal">
        {roleLabel(member.role)}
      </Badge>
      {member.workspaceRoles?.map((r) => (
        <Badge key={r} variant="secondary" className="font-normal" data-testid={`member-workspace-role-${member.id}`}>
          {r} · every team
        </Badge>
      ))}
    </span>
  );
}

function columns(canManage: boolean, showTeam: boolean, onRole: (m: Member) => void, onRemove: (m: Member) => void): ColumnDef<Member>[] {
  return [
    ...(canManage ? [selectColumn<Member>((m) => m.name)] : []),
    idColumn<Member>((m) => m.id),
    {
      id: 'name',
      accessorFn: (m) => `${m.name} ${m.email}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Member" />, meta: { kind: 'name' },
      cell: ({ row }) => (
        <div className="flex min-w-44 items-center gap-3 sm:min-w-52">
          <Avatar aria-hidden="true">
            <AvatarFallback className="text-xs font-medium">{initials(row.original.name)}</AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <div className="truncate font-medium">{row.original.name}</div>
            <div className="truncate text-xs text-muted-foreground">{row.original.email}</div>
            {/* On a phone the role rides under the person, beside the pinned name; from sm up it has its column. */}
            <div className="mt-1 sm:hidden" data-testid={`member-role-inline-${row.original.id}`}>
              <MemberRoles member={row.original} />
            </div>
          </div>
        </div>
      ),
      enableHiding: false,
    },
    ...(showTeam ? [{ accessorKey: 'teamId', header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />, meta: { kind: 'status' }, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.team}</span>, filterFn: facetFilterFn } as ColumnDef<Member>] : []),
    { accessorKey: 'role', header: ({ column }) => <DataTableColumnHeader column={column} title="Role" />, meta: { kind: 'status', className: 'max-sm:hidden' }, cell: ({ row }) => <MemberRoles member={row.original} />, filterFn: facetFilterFn },
    {
      accessorKey: 'status',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, meta: { kind: 'status' },
      cell: ({ row }) =>
        row.original.status === 'invited' ? <span className="text-xs text-warning-text">Invited {relativeTime(row.original.invitedAt)}</span> : <span className="text-xs text-muted-foreground">Active</span>,
      filterFn: facetFilterFn,
    },
    ...(canManage ? [actionsColumn(onRole, onRemove)] : []),
  ];
}

function actionsColumn(onRole: (m: Member) => void, onRemove: (m: Member) => void): ColumnDef<Member> {
  return {
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
  };
}

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'invited', label: 'Invited' },
];

/**
 * The team's people and their roles (c-077): everyone reads the list, and an admin invites, changes roles and removes.
 * platform-service refuses the same writes from anyone else with 403 admin_required, keeps the last admin, and ends a
 * removed member's sessions at once. An invite's link is shown once, in a dialog, because no email is sent.
 */
export function MembersPanel({ inviteOpen, onInviteOpenChange }: { inviteOpen: boolean; onInviteOpenChange: (open: boolean) => void }) {
  const { team, teams } = useTeam();
  const canManage = useCan('access', 'manage') === true;
  const list = useListParams<MemberFilters>('name', 20);
  const query = useMembers(list.params);
  const facets = query.data?.facets ?? {};
  // A list from one team has one Team value on every row; the column and facet earn their width only when it varies.
  const showTeam = Object.keys(facets.teamId ?? {}).length > 1 || !!list.params.filters?.teamId?.length;
  const invite = useInviteMembers();
  const currentTeamOnly = useInvitesToCurrentTeam();
  const setRole = useSetMemberRole();
  const remove = useRemoveMembers();
  const [links, setLinks] = React.useState<{ email: string; url: string }[]>([]);
  const [action, setAction] = React.useState<{ kind: 'role' | 'remove'; rows: Member[] } | null>(null);
  const shown = useSticky(action);
  const [resetKey, setResetKey] = React.useState(0);

  const router = useRouter();
  // A person who has joined opens their own page: what they can do and which role grants it (c-150).
  const rows = React.useMemo(
    () => (query.data?.data ?? []).map((m) => ({ ...m, onRowClick: m.userId ? () => router.push(`/access/people/${encodeURIComponent(m.userId!)}`) : undefined })),
    [query.data, router],
  );
  const cols = React.useMemo(() => columns(canManage, showTeam, (m) => setAction({ kind: 'role', rows: [m] }), (m) => setAction({ kind: 'remove', rows: [m] })), [canManage, showTeam]);
  const withCounts = (column: string, opts: { label: string; value: string }[]) => opts.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const nameOf = (id: string) => shown?.rows.find((m) => m.id === id)?.name ?? id;

  return (
    <>
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="members" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={rows}
          getRowId={(m) => m.id}
          searchColumn="name"
          searchPlaceholder="Search names or emails…"
          filters={[
            { column: 'role', title: 'Role', options: withCounts('role', MEMBER_ROLES.map((r) => ({ value: r.value, label: r.label }))) },
            { column: 'status', title: 'Status', options: withCounts('status', STATUS_OPTIONS) },
            ...(showTeam ? [{ column: 'teamId', title: 'Team', options: withCounts('teamId', teams.map((t) => ({ value: t.id, label: t.name }))) }] : []),
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={
            canManage
              ? [
                  { label: 'Change role', icon: UserCog, variant: 'outline', onClick: (rows) => setAction({ kind: 'role', rows }) },
                  { label: 'Remove', icon: UserX, variant: 'destructive', onClick: (rows) => setAction({ kind: 'remove', rows }) },
                ]
              : undefined
          }
          serverPagination={{
            enabled: true,
            total: query.data?.pagination.total ?? 0,
            page: list.pagination.page,
            pageSize: list.pagination.pageSize,
            totalPages: query.data?.pagination.totalPages,
            onPaginationChange: list.setPagination,
            isLoading: query.isFetching && query.isPlaceholderData,
          }}
          emptyState={<ListEmpty icon={Users} noun="members" filtered={list.isFiltered} createLabel={canManage ? 'Invite' : undefined} onCreate={() => onInviteOpenChange(true)} description="Invite the people who build, review and watch this team’s work." />}
        />
      )}

      <InviteDialog
        open={inviteOpen}
        onOpenChange={onInviteOpenChange}
        teamName={team?.name ?? 'team'}
        teams={team?.scope === 'all' && !currentTeamOnly ? teams.map((t) => ({ id: t.id, name: t.name })) : undefined}
        defaultTeamId={team?.id}
        roles={MEMBER_ROLES}
        isPending={invite.isPending}
        onSubmit={async (input) => {
          const res = await invite.mutateAsync(input);
          toastBulk(res, 'Invited', 'person');
          setLinks((res.invites ?? []).map((i) => ({ email: i.email, url: `${window.location.origin}/invite/${i.token}` })));
        }}
      />
      <InviteLinksDialog links={links} onClose={() => setLinks([])} />
      <BulkFieldDialog
        open={action?.kind === 'role'}
        onOpenChange={(o) => !o && setAction(null)}
        title={shown?.rows.length === 1 ? `Change role for ${shown.rows[0].name}` : `Change role for ${shown?.rows.length ?? 0} members`}
        description="Takes effect when their sign-in next refreshes, within minutes. A team always keeps at least one admin."
        fieldLabel="Role"
        options={MEMBER_ROLES.map((r) => r.label)}
        names={(shown?.rows ?? []).map((m) => m.name)}
        confirmLabel="Change role"
        isPending={setRole.isPending}
        onConfirm={async (label) => {
          const role = MEMBER_ROLES.find((r) => r.label === label)!.value;
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
        description="They lose access to this team at once, and their API keys in it stop working. You can’t remove a team’s last admin."
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
    </>
  );
}
