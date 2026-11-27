'use client';

import * as React from 'react';
import type { LegacyColumnDef as ColumnDef } from '@tanstack/react-table/legacy';
import { MailPlus, Unlink, UserCog, Users, UserX } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { MEMBER_ROLES, roleLabel } from '@/components/access/roles';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
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
import { Button } from '@/components/ui/button';
import { useCan } from '@/hooks/me-queries';
import { useInviteMembers, useInvitesToCurrentTeam, useMembers, useReinviteMembers, useRemoveMembers, useSetMemberRole, useUnlinkMembers } from '@/hooks/settings-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { useTeam, useTeamsNamed } from '@/hooks/use-team';
import { teamLabel } from '@/components/shared/team-name';
import { initials, relativeTime } from '@/lib/format';
import type { Member, MemberFilters } from '@/lib/types/settings';
import { ListCell } from '@/components/shared/table-cells';
import { serverPagination } from '@/components/shared/server-pagination';

/**
 * One role label per person: their role in this team. A role they hold in every team that adds to it (the same role
 * again adds nothing) reads as one muted sentence under the label, so the label never stacks chips.
 */
function MemberRoles({ member }: { member: Member }) {
  const label = roleLabel(member.role);
  const extra = (member.workspaceRoles ?? []).filter((r) => r.toLowerCase() !== label.toLowerCase());
  return (
    <span className="flex flex-col items-start gap-1">
      <Badge variant={member.role === 'admin' ? 'secondary' : 'outline'} className="font-normal">
        {label}
      </Badge>
      {extra.length > 0 && (
        <span className="text-xs text-muted-foreground" data-testid={`member-workspace-role-${member.id}`}>
          Also <ListCell values={extra} shown={1} label="Also held in every team" className="inline-flex align-bottom" />
        </span>
      )}
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
        row.original.status === 'invited' ? (
          <span className="text-xs text-warning-text">Invited {relativeTime(row.original.invitedAt)}</span>
        ) : (
          <span className="flex flex-col items-start gap-0.5">
            <span className="text-xs text-muted-foreground">Active</span>
            {row.original.needsInvite && (
              <Badge variant="outline" className="border-warning/40 font-normal text-warning-text" data-testid={`member-needs-invite-${row.original.id}`}>
                Needs a new invite
              </Badge>
            )}
            {row.original.linksOwnSession && (
              <span className="max-w-48 text-xs text-muted-foreground" data-testid={`member-links-own-${row.original.id}`}>
                Link from your own session after a password reset
              </span>
            )}
          </span>
        ),
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
 * The team's people and their roles: everyone reads the list, and an admin invites, changes roles and removes.
 * platform-service refuses the same writes from anyone else with 403 admin_required, keeps the last admin, and ends a
 * removed member's sessions at once. An invite's link is shown once, in a dialog, because no email is sent.
 */
/** The columns platform-service orders members by (`sortBy` name, role, status or teamId). */
const SORT_COLUMNS = { name: 'name', role: 'role', status: 'status', teamId: 'teamId' };

export function MembersPanel({ inviteOpen, onInviteOpenChange }: { inviteOpen: boolean; onInviteOpenChange: (open: boolean) => void }) {
  const { team } = useTeam();
  const canManage = useCan('access', 'manage') === true;
  const canEdit = useCan('access', 'edit') === true;
  const list = useListParams<MemberFilters>('name', 20, undefined, SORT_COLUMNS);
  const query = useMembers(list.params);
  const facets = query.data?.facets ?? {};
  const teams = useTeamsNamed(Object.keys(facets.teamId ?? {}));
  // A list from one team has one Team value on every row; the column and facet earn their width only when it varies.
  const showTeam = Object.keys(facets.teamId ?? {}).length > 1 || !!list.params.filters?.teamId?.length;
  const invite = useInviteMembers();
  const currentTeamOnly = useInvitesToCurrentTeam();
  const setRole = useSetMemberRole();
  const remove = useRemoveMembers();
  const reinvite = useReinviteMembers();
  const unlink = useUnlinkMembers();
  const [links, setLinks] = React.useState<{ email: string; url: string }[]>([]);
  const [action, setAction] = React.useState<{ kind: 'role' | 'remove' | 'unlink' | 'reinvite'; rows: Member[] } | null>(null);
  const shown = useSticky(action);
  const [resetKey, setResetKey] = React.useState(0);

  const router = useRouter();
  // A person who has joined opens their own page: what they can do and which role grants it.
  const rows = React.useMemo(
    () => (query.data?.data ?? []).map((m) => ({ ...m, onRowClick: m.userId ? () => router.push(`/govern/access/people/${encodeURIComponent(m.userId!)}`) : undefined })),
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
        <QueryError what="members" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
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
            ...(showTeam ? [{ column: 'teamId', title: 'Team', options: withCounts('teamId', Object.keys(facets.teamId ?? {}).map((id) => ({ value: id, label: teamLabel(id, teams) }))) }] : []),
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={
            canManage
              ? [
                  { label: 'Change role', icon: UserCog, variant: 'outline', onClick: (rows) => setAction({ kind: 'role', rows }) },
                  { label: 'Resend invite', icon: MailPlus, variant: 'outline', onClick: (rows) => setAction({ kind: 'reinvite', rows }) },
                  ...(canEdit ? [{ label: 'Unlink sign-in', icon: Unlink, variant: 'outline' as const, onClick: (rows: Member[]) => setAction({ kind: 'unlink', rows }) }] : []),
                  { label: 'Remove', icon: UserX, variant: 'destructive', onClick: (rows) => setAction({ kind: 'remove', rows }) },
                ]
              : undefined
          }
          toolbarExtra={
            canManage ? (
              <Button variant="outline" size="sm" onClick={() => setAction({ kind: 'reinvite', rows: [] })} data-testid="reinvite-affected">
                <MailPlus className="size-4" /> Resend invites
              </Button>
            ) : undefined
          }
          serverPagination={serverPagination(list, query)}
          serverSorting={list.serverSort}
          emptyState={<ListEmpty icon={Users} noun="members" filtered={list.isFiltered} createLabel={canManage ? 'Invite' : undefined} onCreate={() => onInviteOpenChange(true)} description="Invite the people who build, review and watch this team’s work." />}
        />
      )}

      <InviteDialog
        open={inviteOpen}
        onOpenChange={onInviteOpenChange}
        teamName={team?.name ?? 'team'}
        pickTeam={team?.scope === 'all' && !currentTeamOnly}
        defaultTeam={team ? { id: team.id, label: team.name } : undefined}
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
      <ConfirmActionDialog
        open={action?.kind === 'reinvite'}
        onOpenChange={(o) => !o && setAction(null)}
        title={shown?.rows.length ? `Send a new invite to ${shown.rows.length === 1 ? shown.rows[0].name : `${shown.rows.length} members`}?` : 'Send new invites to everyone who needs one?'}
        consequence="Each person who cannot sign in gets a link by email, to their own address only. It works once, expires in 7 days, and links their company sign-in without changing their role. People who do not need one are skipped."
        runsNow
        note="No link is shown here."
        confirmLabel="Send"
        isPending={reinvite.isPending}
        onConfirm={async () => {
          try {
            const res = await reinvite.mutateAsync(shown?.rows.length ? shown.rows.map((m) => m.id) : undefined);
            if (res.mailed.length) toast.success(`Mailed ${res.mailed.length} ${res.mailed.length === 1 ? 'invite' : 'invites'}`);
            else if (!res.skipped.length) toast('Nobody needs a new invite');
            if (res.skipped.length) toastBulk({ updated: [], skipped: res.skipped }, 'Mailed', 'invite', nameOf);
            setAction(null);
            setResetKey((k) => k + 1);
          } catch (e) {
            toast.error('Couldn’t send the invites', { description: (e as Error).message });
          }
        }}
      />
      <DeleteDialog
        open={action?.kind === 'unlink'}
        onOpenChange={(o) => !o && setAction(null)}
        entityType="company sign-in"
        verb="Unlink"
        entityName={shown?.rows.length === 1 ? shown.rows[0].name : undefined}
        count={shown && shown.rows.length > 1 ? shown.rows.length : undefined}
        description="They can no longer sign in through the company provider until they link it again, and any session it opened ends now. Their account, role and data stay."
        confirmText="Unlink"
        isLoading={unlink.isPending}
        onConfirm={async () => {
          try {
            toastBulk(await unlink.mutateAsync(action!.rows.map((m) => m.id)), 'Unlinked', 'sign-in', nameOf);
            setAction(null);
            setResetKey((k) => k + 1);
          } catch (e) {
            toast.error('Couldn’t unlink', { description: (e as Error).message });
          }
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
