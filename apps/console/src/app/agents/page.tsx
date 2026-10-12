'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Bot, Building2, ExternalLink, LayoutTemplate, Pause, Play, Plus, Trash2 } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { AgentAvatar, AgentCard, ChannelList } from '@/components/agents/agent-card';
import { NewAgentDialog } from '@/components/agents/new-agent-dialog';
import { TemplateWizard } from '@/components/agents/template-wizard';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BulkConfirmDialog, BulkFieldDialog, SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { selectColumn } from '@/components/shared/select-column';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { AgentAvailabilityBadge, AVAILABILITY_LABEL } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePromptGenerator } from '@/hooks/prompt-queries';
import { agentsBulkSupported, useAgents, useBulkDeleteAgents, useBulkUpdateAgents, useCreateAgent, useDeleteAgent, useLookups, useModelAliases, useTools } from '@/hooks/queries';
import { useSkillCandidates } from '@/hooks/skill-queries';
import { useCreateFromTemplate, useTemplate, useTemplates } from '@/hooks/template-queries';
import { useCreateParam } from '@/hooks/use-create-param';
import { useTabParam } from '@/hooks/use-tab-param';
import { useTeam } from '@/hooks/use-team';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { count, pct, plural, relativeTime } from '@/lib/format';
import type { Agent } from '@/lib/types/domain';
import type { AgentFilters } from '@/lib/types/query';
import type { SkillCandidateScope } from '@/lib/types/skills';

import { TemplatesTab } from './_parts/templates-tab';

type Row = Agent & { onRowClick: (a: Agent) => void };

const TABS = ['agents', 'templates'] as const;
const ALL_TOOLS = { page: 1, pageSize: 100 };

const AVAILABILITY_OPTIONS = (['published', 'not_published', 'paused'] as const).map((value) => ({ value, label: AVAILABILITY_LABEL[value] }));

function columns(open: (a: Agent) => void, onDelete: (a: Agent) => void): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((a) => a.name),
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Agent" />,
      cell: ({ row }) => (
        <div className="flex min-w-56 items-center gap-3">
          <AgentAvatar name={row.original.name} className="size-8 text-xs" />
          <div className="min-w-0">
            <div className="font-medium">{row.original.name}</div>
            <div className="truncate text-xs text-muted-foreground">{row.original.role}</div>
          </div>
        </div>
      ),
      enableHiding: false,
    },
    {
      accessorKey: 'owner',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Owner" />,
      cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.owner}</span>,
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
              { label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (r) => onDelete(r.original) },
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
  const { data: lookups } = useLookups();
  const models = useModelAliases().data ?? [];
  const create = useCreateFromTemplate();
  const [tab, setTab] = useTabParam(TABS, 'agents');
  const { team } = useTeam();
  const [templateId, setTemplateId] = React.useState<string | null>(null);
  const [fromTab, setFromTab] = React.useState(false);
  const created = React.useRef<string | null>(null);
  const [tplSearch, setTplSearch] = React.useState('');
  const deferredSearch = React.useDeferredValue(tplSearch);
  const remove = useDeleteAgent();
  const [createOpen, setCreateOpen, createKind] = useCreateParam();
  // `?create=template` opens the template wizard; any other `?create` opens the blank one-screen create.
  const wizardOpen = createOpen && createKind === 'template';
  const blankOpen = createOpen && createKind !== 'template';
  const createBlank = useCreateAgent();
  const templates = useTemplates({ page: 1, pageSize: 50, search: deferredSearch || undefined, filters: { status: ['published'] } }, wizardOpen);
  const template = useTemplate(wizardOpen ? templateId : null);
  const teamTools = useTools(ALL_TOOLS);
  const generator = usePromptGenerator();
  const [skillScope, setSkillScope] = React.useState<SkillCandidateScope | null>(null);
  const skillCandidates = useSkillCandidates(skillScope);
  const openCreate = (kind: 'template' | '1') => {
    const next = new URLSearchParams(window.location.search);
    next.set('create', kind);
    router.replace(`/agents?${next.toString()}`, { scroll: false });
  };
  const newAgent = () => openCreate('1');
  const startFromTemplate = () => (setTemplateId(null), setFromTab(false), openCreate('template'));
  const openTemplate = (id: string) => (setTemplateId(id), setFromTab(true), openCreate('template'));
  const [deleting, setDeleting] = React.useState<Agent | null>(null);
  const bulkUpdate = useBulkUpdateAgents();
  const bulkDelete = useBulkDeleteAgents();
  const [bulk, setBulk] = React.useState<{ kind: 'pause' | 'resume' | 'owner' | 'delete'; rows: Agent[] } | null>(null);
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
  const cols = React.useMemo(() => columns(open, setDeleting), [open]);
  const rows: Row[] = React.useMemo(() => (query.data?.data ?? []).map((a) => ({ ...a, onRowClick: open, href: `/agents/${a.id}` })), [query.data, open]);
  const facets = query.data?.facets ?? {};

  return (
    <PageLayout
      icon={Bot}
      title="Agents"
      description="Each agent has a job, a model, the tools it may call and the knowledge it may cite"
      tabs={
        <Tabs value={tab} onValueChange={(t) => setTab(t as (typeof TABS)[number])}>
          <TabsList>
            <TabsTrigger value="agents">Agents</TabsTrigger>
            <TabsTrigger value="templates" data-testid="templates-tab-trigger">
              Templates
            </TabsTrigger>
          </TabsList>
        </Tabs>
      }
      actions={
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={startFromTemplate} data-testid="start-from-template-button">
            <LayoutTemplate className="size-4" /> Start from template
          </Button>
          <Button onClick={newAgent} data-testid="create-agent-button">
            <Plus className="size-4" /> New agent
          </Button>
        </div>
      }
    >
      {tab === 'templates' ? (
        <TemplatesTab onUse={openTemplate} />
      ) : query.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : query.isError && !query.data ? (
        <QueryError what="agents" onRetry={() => query.refetch()} retrying={query.isFetching} />
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
            { column: 'owner', title: 'Owner', options: (lookups?.owners ?? []).map((o) => ({ label: o, value: o, count: facets.owner?.[o] ?? 0 })) },
          ]}
          onColumnFiltersChange={list.onColumnFiltersChange}
          selectionResetKey={resetKey}
          bulkActions={
            agentsBulkSupported
              ? [
                  { label: 'Pause', icon: Pause, variant: 'outline', onClick: (rows) => setBulk({ kind: 'pause', rows }) },
                  { label: 'Resume', icon: Play, variant: 'outline', onClick: (rows) => setBulk({ kind: 'resume', rows }) },
                  { label: 'Change owner', icon: Building2, variant: 'outline', onClick: (rows) => setBulk({ kind: 'owner', rows }) },
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
              createLabel="New agent"
              onCreate={newAgent}
            />
          }
        />
      )}

      <NewAgentDialog
        open={blankOpen}
        onOpenChange={(o) => setCreateOpen(o)}
        models={models}
        owner={team?.scope === 'owned' ? team.ownerGroups[0] : (lookups?.owners[0] ?? '')}
        isPending={createBlank.isPending}
        onSubmit={async (input) => {
          const a = await createBlank.mutateAsync(input);
          toast.success(`Created ${a.name} as a draft`, { description: 'Write its instructions and grant tools here. Request publish when it is ready.' });
          router.push(`/agents/${a.id}`);
        }}
      />
      <TemplateWizard
        open={wizardOpen}
        onOpenChange={(o) => {
          if (!o) setTplSearch('');
          // After a create, open the new agent instead of only dropping ?create (a replace would undo the push).
          if (!o && created.current) return router.push(`/agents/${created.current}`), (created.current = null);
          setCreateOpen(o);
        }}
        templates={templates.data?.data ?? []}
        templatesLoading={templates.isPending}
        templatesError={templates.isError && !templates.data}
        onRetryTemplates={() => templates.refetch()}
        search={tplSearch}
        onSearchChange={setTplSearch}
        templateId={templateId}
        onTemplateChange={setTemplateId}
        detail={template.data}
        detailLoading={template.isFetching && !template.data}
        startAtConfigure={fromTab}
        lookups={lookups}
        models={models}
        defaultOwner={team?.scope === 'owned' ? team.ownerGroups[0] : undefined}
        tools={teamTools.data?.data.filter((t) => t.enabled) ?? []}
        generator={generator}
        skillCandidates={{ data: skillCandidates.data, loading: !!skillScope && (skillCandidates.isPending || skillCandidates.isPlaceholderData), error: skillCandidates.isError && !skillCandidates.data, onRetry: () => skillCandidates.refetch() }}
        onSkillScopeChange={setSkillScope}
        isPending={create.isPending}
        onCreate={async (input) => {
          const res = await create.mutateAsync(input);
          const added = [res.testsAdded ? `${plural(res.testsAdded, 'starter test')} added to its evals` : '', res.skillsAttached ? `${plural(res.skillsAttached, 'skill')} attached` : ''].filter(Boolean);
          toast.success(`Created ${res.agentName}`, { description: `${added.length ? `${added.join('; ')}. ` : ''}Add it to a workflow to put it to work.` });
          created.current = res.agentId;
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
      <BulkFieldDialog
        open={bulk?.kind === 'owner'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Change owner of ${names.length} agents`}
        description="The owning team is accountable for the agent's behaviour and its reviews."
        fieldLabel="Team"
        options={lookups?.owners ?? []}
        names={names}
        confirmLabel="Change owner"
        isPending={bulkUpdate.isPending}
        onConfirm={async (owner) => {
          const res = await bulkUpdate.mutateAsync({ ids: bulk!.rows.map((a) => a.id), patch: { owner } });
          toastBulk(res, 'Moved', 'agent', nameOf);
          finish();
        }}
      />
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
