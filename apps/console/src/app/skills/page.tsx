'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Archive, Download, ExternalLink, FilePlus2, Inbox, Pin, Sparkles, Trash2, Upload, Users } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { openLink } from '@/components/files/file-actions';
import { PageLayout } from '@/components/page-layout';
import { SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { idColumn } from '@/components/shared/id-column';
import { selectColumn } from '@/components/shared/select-column';
import { announcePublish } from '@/components/shared/publish-result';
import { GenerateSkillDialog } from '@/components/skills/generate-skill-dialog';
import { DeprecateSkillDialog, ImportSkillDialog, NewSkillDialog } from '@/components/skills/skill-dialogs';
import { ORIGIN, SkillStatusBadge, STATUS_LABEL } from '@/components/skills/skill-meta';
import { SKILL_LOADING_LABEL, SKILL_LOADING_OPTIONS } from '@/components/skills/skill-loading';
import { Button } from '@/components/ui/button';
import { useDownloadFile } from '@/hooks/file-queries';
import { useBulkDeleteSkills, useBulkDeprecateSkills, useCreateSkill, useExportSkills, useImportSkill, useSkillGeneratorBackend, useSkillImportPreview, useSkillOptions, useSkills } from '@/hooks/skill-queries';
import { useCreateParam } from '@/hooks/use-create-param';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import { useCanBuild } from '@/hooks/me-queries';
import { useTeam } from '@/hooks/use-team';
import { pct, plural, relativeTime } from '@/lib/format';
import type { Skill, SkillFilters, SkillOrigin, SkillStatus, SkillView } from '@/lib/types/skills';

type Row = Skill & { onRowClick: (s: Skill) => void; href: string; rowTestId: string };

const STATUS_OPTIONS = (Object.keys(STATUS_LABEL) as SkillStatus[]).map((v) => ({ value: v, label: STATUS_LABEL[v] }));
const ORIGIN_OPTIONS = (Object.keys(ORIGIN) as SkillOrigin[]).map((v) => ({ value: v, label: ORIGIN[v].label, icon: ORIGIN[v].icon }));
/** Tools and knowledge bases are filtered on the server, which matches a skill holding any selected value. */
const serverFiltered = () => true;
const NO_TEAMS: string[] = [];

function columns(open: (s: Skill) => void, onExport: (s: Skill) => void): ColumnDef<Row>[] {
  return [
    selectColumn<Row>((s) => s.name),
    idColumn<Row>((s) => s.id),
    {
      id: 'name',
      accessorFn: (s) => s.name,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Skill" />,
      cell: ({ row }) => {
        const Icon = ORIGIN[row.original.origin].icon;
        return (
          <div className="flex w-60 max-w-60 items-start gap-2.5" title={row.original.name}>
            <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-label={ORIGIN[row.original.origin].label} />
            <div className="min-w-0">
              <div className="truncate font-medium">{row.original.name}</div>
              <code className="block truncate font-mono text-[11px] text-muted-foreground">{row.original.slug}</code>
            </div>
          </div>
        );
      },
      enableHiding: false,
    },
    {
      accessorKey: 'useWhen',
      header: 'Use when',
      cell: ({ row }) => (
        <p className="line-clamp-2 w-72 text-xs whitespace-normal text-muted-foreground" title={row.original.useWhen}>
          {row.original.loading === 'always' ? 'Every turn, after the agent’s instructions' : row.original.useWhen}
        </p>
      ),
      enableSorting: false,
    },
    {
      accessorKey: 'loading',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Loading" />,
      cell: ({ row }) => <span className="text-xs whitespace-nowrap">{SKILL_LOADING_LABEL[row.original.loading]}</span>,
      filterFn: facetFilterFn,
      enableSorting: false,
    },
    {
      accessorKey: 'ownerTeam',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Owner team" />,
      cell: ({ row }) => <span className="text-xs whitespace-nowrap">{row.original.ownerTeam}</span>,
      filterFn: facetFilterFn,
    },
    {
      accessorKey: 'status',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
      cell: ({ row }) => <SkillStatusBadge status={row.original.status} />,
      filterFn: facetFilterFn,
    },
    {
      accessorKey: 'version',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />,
      cell: ({ row }) => (
        <div className="text-xs whitespace-nowrap tabular-nums">
          <span className="font-mono">{row.original.publishedVersion ? `v${row.original.publishedVersion}` : '—'}</span>
          {row.original.draftVersion && row.original.draftVersion !== row.original.publishedVersion && <div className="text-muted-foreground">draft v{row.original.draftVersion}</div>}
        </div>
      ),
    },
    {
      accessorKey: 'usedBy',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Used by" />,
      cell: ({ row }) => (
        <span className={row.original.usedBy ? 'text-xs whitespace-nowrap tabular-nums' : 'text-xs text-muted-foreground'}>
          {row.original.usedBy ? plural(row.original.usedBy, 'agent') : 'Unused'}
          {row.original.liveAgents > 0 && <span className="text-muted-foreground"> · {row.original.liveAgents} live</span>}
        </span>
      ),
    },
    {
      id: 'scope',
      accessorFn: (s) => s.toolCount + s.kbCount,
      header: 'Tools · KBs',
      cell: ({ row }) => (
        <span className="text-xs whitespace-nowrap tabular-nums">
          {plural(row.original.toolCount, 'tool')} · {plural(row.original.kbCount, 'KB', 'KBs')}
        </span>
      ),
    },
    {
      accessorKey: 'lastEvalPassRate',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Last tests" />,
      cell: ({ row }) => {
        const r = row.original.lastEvalPassRate;
        return <span className={r === null ? 'text-muted-foreground' : r < 1 ? 'font-medium text-warning-text tabular-nums' : 'tabular-nums'}>{r === null ? 'Not run' : pct(r)}</span>;
      },
      sortUndefined: 'last',
    },
    {
      accessorKey: 'updatedAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Updated" />,
      cell: ({ row }) => (
        <span className="text-xs whitespace-nowrap text-muted-foreground" title={`${row.original.updatedBy}`}>
          {relativeTime(row.original.updatedAt)}
        </span>
      ),
    },
    { id: 'tools', accessorFn: () => '', header: 'Tools', filterFn: serverFiltered, enableHiding: false, enableSorting: false },
    { id: 'knowledgeBases', accessorFn: () => '', header: 'Knowledge bases', filterFn: serverFiltered, enableHiding: false, enableSorting: false },
    { accessorKey: 'origin', header: 'Origin', filterFn: facetFilterFn, enableHiding: false },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Open', icon: ExternalLink, onClick: (r) => open(r.original) },
              { label: 'Export SKILL.md', icon: Download, onClick: (r) => onExport(r.original) },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

const VIEWS: SkillView[] = ['all', 'published', 'always', 'drafts', 'in_review', 'deprecated', 'unused'];

export default function SkillsPage() {
  const router = useRouter();
  const search = useSearchParams();
  const [view, setView] = React.useState<SkillView>(() => (VIEWS.includes(search.get('view') as SkillView) ? (search.get('view') as SkillView) : 'all'));
  const list = useListParams<SkillFilters>('name');
  const query = useSkills({ ...list.params, view });
  const options = useSkillOptions();
  const { team } = useTeam();
  const defaultTeam = team?.scope === 'owned' ? team.ownerGroups[0] : undefined;
  const canBuild = useCanBuild();
  const [createOpen, setCreateOpen, createKind] = useCreateParam();
  const generateOpen = createOpen && canBuild && createKind === 'generate';
  // After a create the page navigates to the new skill; closing the dialog must not replace that navigation.
  const leaving = React.useRef(false);
  const closeCreate = (o: boolean) => {
    if (!o && leaving.current) return;
    setCreateOpen(o);
  };
  const blankOpen = createOpen && canBuild && createKind !== 'generate';
  const backend = useSkillGeneratorBackend(generateOpen);
  const create = useCreateSkill();
  const [importOpen, setImportOpen] = React.useState(false);
  const [importFileId, setImportFileId] = React.useState<string | undefined>();
  const preview = useSkillImportPreview(importOpen ? importFileId : undefined);
  const importSkill = useImportSkill();
  const exportSkills = useExportSkills();
  const download = useDownloadFile();
  const bulkDeprecate = useBulkDeprecateSkills();
  const bulkDelete = useBulkDeleteSkills();
  const [bulk, setBulk] = React.useState<{ kind: 'deprecate' | 'delete'; rows: Skill[] } | null>(null);
  const shown = useSticky(bulk);
  const [resetKey, setResetKey] = React.useState(0);
  const names = (shown?.rows ?? []).map((s) => s.name);
  const nameOf = (id: string) => shown?.rows.find((s) => s.id === id)?.name ?? id;
  const finish = () => {
    setBulk(null);
    setResetKey((k) => k + 1);
  };
  const openCreate = (kind: 'generate' | '1') => {
    const next = new URLSearchParams(window.location.search);
    next.set('create', kind);
    router.replace(`/skills?${next.toString()}`, { scroll: false });
  };

  const runExport = async (rows: Skill[]) => {
    try {
      const f = await exportSkills.mutateAsync({ ids: rows.map((s) => s.id) });
      toast.success(`Exported ${rows.length === 1 ? rows[0].name : plural(rows.length, 'skill')}`, {
        description: `${f.name} is in Files.`,
        action: { label: 'Download', onClick: async () => openLink(await download.mutateAsync(f.id), f.name) },
      });
      setResetKey((k) => k + 1);
    } catch (e) {
      toast.error('Couldn’t export', { description: (e as Error).message });
    }
  };

  const rows: Row[] = React.useMemo(
    () => (query.data?.data ?? []).map((s) => ({ ...s, href: `/skills/${s.id}`, onRowClick: (x: Skill) => router.push(`/skills/${x.id}`), rowTestId: `skill-row-${s.id}` })),
    [query.data, router],
  );
  const cols = React.useMemo(() => columns((s) => router.push(`/skills/${s.id}`), (s) => void runExport([s])), [router]); // eslint-disable-line react-hooks/exhaustive-deps
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, opts: { value: string; label: string }[]) => opts.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const facetOptions = (column: string) => withCounts(column, Object.keys(facets[column] ?? {}).sort().map((v) => ({ value: v, label: v })));
  const counts = query.data?.viewCounts;
  const teams = options.data?.teams ?? NO_TEAMS;

  return (
    <PageLayout
      switcher
      icon={Sparkles}
      title="Skills"
      description="Reusable procedures agents load when a task matches, and shared wording that is in every turn"
      actions={
        canBuild && (
        <>
          <Button variant="outline" onClick={() => setImportOpen(true)} data-testid="import-skill-button">
            <Upload className="size-4" /> Import
          </Button>
          <Button variant="outline" onClick={() => openCreate('1')} data-testid="new-skill-button">
            <FilePlus2 className="size-4" /> New blank skill
          </Button>
          <Button onClick={() => openCreate('generate')} data-testid="generate-skill-button">
            <Sparkles className="size-4" /> Generate skill
          </Button>
        </>
        )
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="skills" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <div className="flex flex-col gap-4">
          <SavedViewTabs
            ariaLabel="Skill views"
            presets={[
              { id: 'all', label: `All · ${counts?.all ?? 0}` },
              { id: 'published', label: `Published · ${counts?.published ?? 0}` },
              { id: 'always', label: `Always on · ${counts?.always ?? 0}`, icon: Pin },
              { id: 'drafts', label: `Drafts · ${counts?.drafts ?? 0}` },
              { id: 'in_review', label: `In review · ${counts?.in_review ?? 0}`, icon: Inbox },
              { id: 'deprecated', label: `Deprecated · ${counts?.deprecated ?? 0}`, icon: Archive },
              { id: 'unused', label: `Unused · ${counts?.unused ?? 0}`, icon: Users },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as SkillView);
              list.reset();
              setResetKey((k) => k + 1);
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />
          <DataTableWithViews
            columns={cols}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="name"
            searchPlaceholder="Search skills…"
            initialColumnVisibility={{ tools: false, knowledgeBases: false, origin: false, scope: true }}
            filters={[
              { column: 'status', title: 'Status', options: withCounts('status', STATUS_OPTIONS) },
              { column: 'loading', title: 'Loading', options: withCounts('loading', SKILL_LOADING_OPTIONS) },
              { column: 'ownerTeam', title: 'Owner team', options: facetOptions('ownerTeam') },
              { column: 'tools', title: 'Tool', options: facetOptions('tools') },
              { column: 'knowledgeBases', title: 'Knowledge base', options: facetOptions('knowledgeBases') },
              { column: 'origin', title: 'Origin', options: withCounts('origin', ORIGIN_OPTIONS) },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            selectionResetKey={resetKey}
            bulkActions={[
              { label: 'Export', icon: Download, variant: 'outline', onClick: (r) => void runExport(r) },
              ...(canBuild
                ? [
                    { label: 'Deprecate', icon: Archive, variant: 'outline' as const, onClick: (r: Skill[]) => setBulk({ kind: 'deprecate', rows: r }) },
                    { label: 'Delete', icon: Trash2, variant: 'destructive' as const, onClick: (r: Skill[]) => setBulk({ kind: 'delete', rows: r }) },
                  ]
                : []),
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
            emptyState={
              <ListEmpty
                icon={Sparkles}
                noun={view === 'all' ? 'skills' : 'skills in this view'}
                filtered={list.isFiltered}
                description={view === 'all' ? 'Generate a skill from a document, past cases or a description, or import a SKILL.md.' : 'Nothing matches this view right now.'}
                createLabel={view === 'all' && canBuild ? 'Generate skill' : undefined}
                onCreate={view === 'all' ? () => openCreate('generate') : undefined}
              />
            }
          />
        </div>
      )}

      <GenerateSkillDialog
        open={generateOpen}
        onOpenChange={closeCreate}
        backend={backend}
        defaultTeam={defaultTeam}
        onSaved={(s, requested) => {
          leaving.current = true;
          if (requested) announcePublish({ name: s.name, version: s.version, live: !s.pendingReviewId, liveNote: 'Agents can attach it now.', decidedBy: `An approver in ${s.ownerTeam}`, reviewId: s.pendingReviewId, openReview: (id) => router.push(`/reviews?review=${id}`) });
          else toast.success(`Saved ${s.name} as a draft`, { description: 'Run its tests, then request review.' });
          router.push(`/skills/${s.id}`);
        }}
      />
      <NewSkillDialog
        open={blankOpen}
        onOpenChange={closeCreate}
        teams={teams}
        defaultTeam={defaultTeam}
        maxUseWhen={options.data?.limits.useWhenMaxChars ?? 1024}
        isPending={create.isPending}
        onSubmit={async (i) => {
          const s = await create.mutateAsync(i);
          leaving.current = true;
          toast.success(`Created ${s.name}`, { description: 'Write the instructions and add tests, then request review.' });
          router.push(`/skills/${s.id}?tab=instructions`);
        }}
      />
      <ImportSkillDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        teams={teams}
        defaultTeam={defaultTeam}
        onFile={setImportFileId}
        preview={preview.data}
        previewLoading={preview.isPending && !!importFileId}
        previewError={preview.isError ? preview.error.message : undefined}
        isPending={importSkill.isPending}
        onImport={async (fileId, ownerTeam) => {
          const s = await importSkill.mutateAsync({ fileId, ownerTeam });
          toast.success(`Imported ${s.name} as a draft`, { description: 'Check the tools it asked for, add tests, then request review.' });
          router.push(`/skills/${s.id}`);
        }}
      />
      <DeprecateSkillDialog
        open={bulk?.kind === 'deprecate'}
        onOpenChange={(o) => !o && setBulk(null)}
        names={names}
        pinnedBy={(shown?.rows ?? []).reduce((n, s) => n + s.usedBy, 0)}
        isPending={bulkDeprecate.isPending}
        onSubmit={async (reason) => {
          const res = await bulkDeprecate.mutateAsync({ ids: bulk!.rows.map((s) => s.id), reason });
          toastBulk(res, 'Deprecated', 'skill', nameOf);
          finish();
        }}
      />
      <DeleteDialog
        open={bulk?.kind === 'delete'}
        onOpenChange={(o) => !o && setBulk(null)}
        entityType="skill"
        count={names.length}
        entityName={names.length === 1 ? names[0] : undefined}
        description="Skills a live agent pins, or with a publish request open, are skipped. Detach them from the agents first."
        isLoading={bulkDelete.isPending}
        onConfirm={async () => {
          const res = await bulkDelete.mutateAsync(bulk!.rows.map((s) => s.id));
          toastBulk(res, 'Deleted', 'skill', nameOf);
          finish();
        }}
      >
        <SelectedList names={names} />
      </DeleteDialog>
    </PageLayout>
  );
}
