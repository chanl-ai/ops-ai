'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Archive, ArchiveRestore, Pencil, Plus, ShieldCheck, Users } from 'lucide-react';
import { toast } from 'sonner';

import { TeamDialog } from '@/components/access/team-dialog';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { StopRowClick } from '@/components/shared/form-field';
import { idColumn } from '@/components/shared/id-column';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useListParams } from '@/hooks/use-list-params';
import { useArchiveWorkspaceTeam, useCreateWorkspaceTeam, useRenameWorkspaceTeam, useRestoreWorkspaceTeam, useWorkspaceTeams, useWorkspaceTeamsEditor } from '@/hooks/workspace-team-queries';
import { shortDate } from '@/lib/format';
import type { WorkspaceTeam, WorkspaceTeamFilters } from '@/lib/types/team';

type Act = { rename: (t: WorkspaceTeam) => void; archive: (t: WorkspaceTeam) => void; restore: (t: WorkspaceTeam) => void };

/** Rename always; Archive or Restore by status. The Security team has no Archive: the server refuses it. */
function rowActions(t: WorkspaceTeam, act: Act) {
  const rename = { label: 'Rename', icon: Pencil, onClick: () => act.rename(t) };
  if (t.status === 'archived') return [rename, { label: 'Restore', icon: ArchiveRestore, onClick: () => act.restore(t) }];
  return t.security ? [rename] : [rename, { label: 'Archive', icon: Archive, variant: 'destructive' as const, onClick: () => act.archive(t) }];
}

const STATUS_LABEL: Record<WorkspaceTeam['status'], string> = { active: 'Active', archived: 'Archived' };

function columns(canManage: boolean, act: Act): ColumnDef<WorkspaceTeam>[] {
  return [
    selectColumn<WorkspaceTeam>((t) => t.name),
    idColumn<WorkspaceTeam>((t) => t.id),
    {
      id: 'name',
      accessorFn: (t) => t.name,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />,
      cell: ({ row }) => (
        <div className="flex min-w-44 items-center gap-2">
          <span className="font-medium">{row.original.name}</span>
          {row.original.security && (
            <Badge variant="outline" className="gap-1 font-normal">
              <ShieldCheck className="size-3" /> Security
            </Badge>
          )}
        </div>
      ),
      enableHiding: false,
    },
    {
      id: 'status',
      accessorFn: (t) => t.status,
      header: 'Status',
      cell: ({ row }) => <Badge variant={row.original.status === 'active' ? 'secondary' : 'outline'}>{STATUS_LABEL[row.original.status]}</Badge>,
      filterFn: () => true,
    },
    { accessorKey: 'memberCount', header: 'Members', cell: ({ row }) => <span className="tabular-nums">{row.original.memberCount}</span> },
    { accessorKey: 'adminCount', header: 'Admins', cell: ({ row }) => <span className={row.original.adminCount === 0 ? 'text-warning-text tabular-nums' : 'tabular-nums'}>{row.original.adminCount}</span> },
    { accessorKey: 'createdAt', header: 'Created', cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{shortDate(row.original.createdAt)}</span> },
    ...(canManage
      ? [
          {
            id: 'actions',
            meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
            cell: ({ row }) => (
              <StopRowClick>
                <DataTableRowActions row={row} actions={rowActions(row.original, act)} />
              </StopRowClick>
            ),
            enableHiding: false,
          } as ColumnDef<WorkspaceTeam>,
        ]
      : []),
  ];
}

/** Every team of the workspace (c-198): workspace admins create, rename, archive and restore them here. */
export default function TeamsPage() {
  const editor = useWorkspaceTeamsEditor();
  const list = useListParams<WorkspaceTeamFilters>('name');
  const canView = !!editor.data?.canView;
  const canManage = !!editor.data?.canManage;
  const query = useWorkspaceTeams(list.params);
  const create = useCreateWorkspaceTeam();
  const rename = useRenameWorkspaceTeam();
  const archive = useArchiveWorkspaceTeam();
  const restore = useRestoreWorkspaceTeam();
  const [dialog, setDialog] = React.useState<{ open: boolean; team: WorkspaceTeam | null }>({ open: false, team: null });
  const [archiving, setArchiving] = React.useState<WorkspaceTeam | null>(null);
  const cols = React.useMemo(
    () =>
      columns(canManage, {
        rename: (t) => setDialog({ open: true, team: t }),
        archive: setArchiving,
        restore: async (t) => {
          try {
            await restore.mutateAsync(t.id);
            toast.success(`Restored ${t.name}`);
          } catch (e) {
            toast.error('Couldn’t restore the team', { description: (e as Error).message });
          }
        },
      }),
    [canManage, restore],
  );

  const body = (() => {
    if (editor.isPending) return <PageSkeleton statCards={0} tableRows={4} />;
    if (!canView) return <EmptyState icon={Users} title="Teams are managed by workspace admins" description="Ask a workspace admin to create, rename or archive a team. Your own team’s people are under Members and roles." testId="teams-no-access" />;
    if (query.isPending) return <PageSkeleton statCards={0} tableRows={4} />;
    if (query.isError && !query.data) return <QueryError what="teams" onRetry={() => query.refetch()} retrying={query.isFetching} />;
    return (
      <DataTableWithViews
        columns={cols}
        data={query.data?.data ?? []}
        getRowId={(t) => t.id}
        searchColumn="name"
        searchPlaceholder="Search teams…"
        filters={[{ column: 'status', title: 'Status', options: [{ label: 'Active', value: 'active' }, { label: 'Archived', value: 'archived' }] }]}
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
        emptyState={<ListEmpty icon={Users} noun="teams" filtered={list.isFiltered} createLabel={canManage ? 'Create team' : undefined} onCreate={canManage ? () => setDialog({ open: true, team: null }) : undefined} description="Each group gets a team that owns its agents, workflows, tools, knowledge and secrets." />}
      />
    );
  })();

  return (
    <PageLayout
      icon={Users}
      title="Teams"
      description="Every team in this workspace. A team owns its work; its admins add people and set their roles."
      actions={
        canManage ? (
          <Button onClick={() => setDialog({ open: true, team: null })} data-testid="teams-create">
            <Plus className="size-4" /> Create team
          </Button>
        ) : undefined
      }
    >
      {body}
      <TeamDialog
        open={dialog.open}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
        team={dialog.team}
        pending={create.isPending || rename.isPending}
        onSubmit={async (input) => {
          if (dialog.team) {
            await rename.mutateAsync({ id: dialog.team.id, name: input.name });
            toast.success(`Renamed to ${input.name}`);
          } else {
            await create.mutateAsync(input);
            toast.success(`Created ${input.name}`);
          }
        }}
      />
      <ConfirmActionDialog
        open={!!archiving}
        onOpenChange={(o) => !o && setArchiving(null)}
        title={`Archive ${archiving?.name ?? 'team'}?`}
        consequence="Its members lose the team at their next sign-in refresh and it takes no new members. What it owns stays its own, and you can restore it."
        runsNow
        note="Restore the team from this list to bring it back."
        confirmLabel="Archive team"
        destructive
        isPending={archive.isPending}
        onConfirm={async () => {
          await archive.mutateAsync(archiving!.id);
          toast.success(`Archived ${archiving!.name}`);
          setArchiving(null);
        }}
      />
    </PageLayout>
  );
}
