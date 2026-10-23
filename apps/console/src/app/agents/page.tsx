'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Bot, ExternalLink, Pause, Play, Plus, Star, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { AgentAvatar, AgentCard, ChannelList } from '@/components/agents/agent-card';
import { MakeDefaultAgentDialog } from '@/components/chat/make-default-agent';
import { NewAgentDialog } from '@/components/agents/new-agent-dialog';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BulkConfirmDialog, SelectedList, toastBulk } from '@/components/shared/bulk';
import { TeamName, teamLabel } from '@/components/shared/team-name';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { idColumn } from '@/components/shared/id-column';
import { selectColumn } from '@/components/shared/select-column';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { AgentAvailabilityBadge, AVAILABILITY_LABEL } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { agentsBulkSupported, useAgents, useBulkDeleteAgents, useBulkUpdateAgents, useCreateAgent, useDeleteAgent, useModelAliases } from '@/hooks/queries';
import { useCreateParam } from '@/hooks/use-create-param';
import { useCanSetDefaultAgent, useDefaultAgent } from '@/hooks/chat-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useTeam } from '@/hooks/use-team';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, pct, plural, relativeTime } from '@/lib/format';
import type { Agent } from '@/lib/types/domain';
import type { AgentFilters } from '@/lib/types/query';

type Row = Agent & { onRowClick: (a: Agent) => void };


const AVAILABILITY_OPTIONS = (['published', 'not_published', 'paused'] as const).map((value) => ({ value, label: AVAILABILITY_LABEL[value] }));

/** `onMakeDefault` is set for team admins only (c-174); `defaultId` marks the agent new chats start on. */
function columns(open: (a: Agent) => void, onDelete: (a: Agent) => void, canBuild: boolean, defaultId?: string, onMakeDefault?: (a: Agent) => void): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((a) => a.name),
    idColumn<Row>((a) => a.id),
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Agent" />,
      cell: ({ row }) => (
        <div className="flex min-w-56 items-center gap-3">
          <AgentAvatar name={row.original.name} className="size-8 text-xs" />
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-medium">
              {row.original.name}
              {row.original.id === defaultId && <Badge variant="secondary">Default</Badge>}
            </div>
            <div className="truncate text-xs text-muted-foreground">{row.original.role}</div>
          </div>
        </div>
      ),
      enableHiding: false,
    },
    {
      accessorKey: 'teamId',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />,
      cell: ({ row }) => <TeamName teamId={row.original.teamId} className="whitespace-nowrap text-muted-foreground" />,
      filterFn: facetFilterFn,
    },
    {
      accessorKey: 'model',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Model" />,
      cell: ({ row }) => <code className="font-mono text-xs">{row.original.model}</code>,
      enableSorting: false,
    },
    { id: 'channels', header: 'Channels', cell: ({ row }) => <ChannelList channels={row.original.channels} /> },
    {
      accessorKey: 'tasks24h',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Tasks · 24h" />,
      cell: ({ row }) => <span className="tabular-nums">{row.original.availability === 'not_published' ? '—' : count(row.original.tasks24h)}</span>,
    },
    {
      accessorKey: 'autoResolvedRate',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Auto-resolved" />,
      cell: ({ row }) => <span className="tabular-nums">{row.original.availability === 'not_published' ? '—' : pct(row.original.autoResolvedRate)}</span>,
    },
    {
      accessorKey: 'availability',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Availability" />,
      cell: ({ row }) => <AgentAvailabilityBadge availability={row.original.availability} />,
      filterFn: facetFilterFn,
    },
    {
      accessorKey: 'updatedAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />,
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-muted-foreground tabular-nums">
          v{row.original.version} · {relativeTime(row.original.updatedAt)}
        </span>
      ),
    },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Open', icon: ExternalLink, onClick: (r) => open(r.original) },
              ...(onMakeDefault && row.original.availability === 'published' && row.original.id !== defaultId
                ? [{ label: 'Make default', icon: Star, onClick: (r: { original: Row }) => onMakeDefault(r.original) }]
                : []),
              ...(canBuild ? [{ label: 'Delete', icon: Trash2, variant: 'destructive' as const, onClick: (r: { original: Row }) => onDelete(r.original) }] : []),
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function AgentsPage() {
  const router = useRouter();
  const list = useListParams<AgentFilters>('name');
  const query = useAgents(list.params);
  const models = useModelAliases().data ?? [];
  const { team, teams } = useTeam();
  const canBuild = useCanBuild();
  const remove = useDeleteAgent();
  // Templates have no API yet (docs/console/strategy.md), so `?create` opens the blank one-screen create only.
  const [createOpen, setCreateOpen] = useCreateParam();
  const blankOpen = createOpen && canBuild;
  const createBlank = useCreateAgent();
  const newAgent = () => {
    const next = new URLSearchParams(window.location.search);
    next.set('create', '1');
    router.replace(`/agents?${next.toString()}`, { scroll: false });
  };
  const [deleting, setDeleting] = React.useState<Agent | null>(null);
  const bulkUpdate = useBulkUpdateAgents();
  const bulkDelete = useBulkDeleteAgents();
  const [bulk, setBulk] = React.useState<{ kind: 'pause' | 'resume' | 'delete'; rows: Agent[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const eligible = (shown?.rows ?? []).filter((x) => x.availability !== 'not_published');
  const names = (shown?.rows ?? []).map((a) => a.name);
  const nameOf = (id: string) => shown?.rows.find((a) => a.id === id)?.name ?? id;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };

  const open = React.useCallback((a: Agent) => router.push(`/agents/${a.id}`), [router]);
  const isAdmin = useCanSetDefaultAgent();
  const defaultId = useDefaultAgent().data?.agentId;
  const [makingDefault, setMakingDefault] = React.useState<Agent>();
  const cols = React.useMemo(() => columns(open, setDeleting, canBuild, defaultId, isAdmin ? setMakingDefault : undefined), [open, canBuild, defaultId, isAdmin]);
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((a) => ({ ...a, onRowClick: open, href: `/agents/${a.id}` })), [query.data, open]);
  const facets = query.data?.facets ?? {};

  return (
    <PageLayout
      icon={Bot}
      title="Agents"
      description="Each agent has a job, a model, the tools it may call and the knowledge it may cite"
      actions={
        canBuild && (
          <Button onClick={newAgent} data-testid="create-agent-button">
            <Plus className="size-4" /> New agent
          </Button>
        )
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : query.isError && !query.data ? (
        <QueryError what="agents" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={rows}
          getRowId={(r) => r.id}
          initialColumnVisibility={{ model: false, updatedAt: false }}
          defaultView="table"
          gridClassName="grid grid-cols-1 gap-4 @3xl/main:grid-cols-2 @6xl/main:grid-cols-3"
          renderGridItem={(a) => <AgentCard agent={a} />}
          searchColumn="name"
          searchPlaceholder="Search agents…"
          filters={[
            { column: 'availability', title: 'Availability', options: AVAILABILITY_OPTIONS.map((o) => ({ ...o, count: facets.availability?.[o.value] ?? 0 })) },
            { column: 'teamId', title: 'Team', options: Object.entries(facets.teamId ?? {}).map(([id, count]) => ({ label: teamLabel(id, teams), value: id, count })) },
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={
            agentsBulkSupported && canBuild
              ? [
                  { label: 'Pause', icon: Pause, variant: 'outline', onClick: (rows) => setBulk({ kind: 'pause', rows }) },
                  { label: 'Resume', icon: Play, variant: 'outline', onClick: (rows) => setBulk({ kind: 'resume', rows }) },
                  { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (rows) => setBulk({ kind: 'delete', rows }) },
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
          emptyState={
            <ListEmpty
              icon={Bot}
              noun="agents"
              filtered={list.isFiltered}
              description="Create an agent, give it tools and knowledge, then add it to a workflow."
              createLabel={canBuild ? 'New agent' : undefined}
              onCreate={newAgent}
            />
          }
        />
      )}

      <NewAgentDialog
        open={blankOpen}
        onOpenChange={(o) => setCreateOpen(o)}
        models={models}
        team={team?.name ?? ''}
        isPending={createBlank.isPending}
        onSubmit={async (input) => {
          const a = await createBlank.mutateAsync(input);
          toast.success(`Created ${a.name} as a draft`, { description: 'Write its instructions and grant tools here. Request publish when it is ready.' });
          router.push(`/agents/${a.id}`);
        }}
      />

      <BulkConfirmDialog
        open={bulk?.kind === 'pause' || bulk?.kind === 'resume'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`${shown?.kind === 'pause' ? 'Pause' : 'Resume'} ${eligible.length === names.length ? plural(names.length, 'agent') : `${eligible.length} of ${plural(names.length, 'agent')}`}`}
        description={shown?.kind === 'pause' ? 'New runs stop using them until they are resumed. Versions, pins and open publish requests are unchanged. Agents never published are skipped.' : 'New runs use their published versions again. Agents never published are skipped.'}
        names={names}
        confirmLabel={shown?.kind === 'pause' ? 'Pause' : 'Resume'}
        isPending={bulkUpdate.isPending}
        onConfirm={async () => {
          const res = await bulkUpdate.mutateAsync({ ids: bulk!.rows.map((a) => a.id), patch: { paused: bulk!.kind === 'pause' } });
          toastBulk(res, bulk!.kind === 'pause' ? 'Paused' : 'Resumed', 'agent', nameOf);
          finish();
        }}
      />
      <MakeDefaultAgentDialog agent={makingDefault} open={!!makingDefault} onOpenChange={(o) => !o && setMakingDefault(undefined)} />
      <DeleteDialog
        open={bulk?.kind === 'delete'}
        onOpenChange={(o) => !o && setBulk(null)}
        entityType="agent"
        count={names.length}
        description="Agents used by a live workflow are skipped. Delete or reassign the step first."
        isLoading={bulkDelete.isPending}
        onConfirm={async () => {
          const res = await bulkDelete.mutateAsync(bulk!.rows.map((a) => a.id));
          toastBulk(res, 'Deleted', 'agent', nameOf);
          finish();
        }}
      >
        <SelectedList names={names} />
      </DeleteDialog>

      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="agent"
        entityName={deleting?.name}
        requireNameConfirmation
        description={deleting?.workflowIds.length ? `${deleting.name} runs in ${plural(deleting.workflowIds.length, 'workflow')}. Those steps fail until another agent is chosen.` : undefined}
        isLoading={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await remove.mutateAsync(deleting.id);
            toast.success(`Deleted ${deleting.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error('Couldn’t delete the agent', { description: (e as Error).message });
          }
        }}
      />
    </PageLayout>
  );
}
