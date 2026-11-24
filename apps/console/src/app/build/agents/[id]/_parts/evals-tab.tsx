'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { FlaskConical, Play, Plus, Trash2, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { EvalCaseDialog } from '@/components/evals/eval-case-dialog';
import { CheckChips, SOURCE_LABEL } from '@/components/evals/eval-meta';
import { costLabel, EvalResultsTable, EvalRunSummary, triggerLabel, versionsLabel } from '@/components/evals/eval-results';
import { ImportEvalCasesDialog } from '@/components/evals/import-eval-cases-dialog';
import { SelectedList, toastBulk } from '@/components/shared/bulk';
import { ListCell } from '@/components/shared/table-cells';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { EmptyState } from '@/components/shared/empty-state';
import { StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { serverPagination } from '@/components/shared/server-pagination';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useAddEvalCases, useBulkDeleteEvalCases, useDeleteEvalCase, useEvalCases, useEvalRun, useEvalRuns, useLatestEvalRun, useRunEvals } from '@/hooks/eval-queries';
import { useCan } from '@/hooks/me-queries';
import { useGrantableTools } from '@/hooks/queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { useCreatedRows } from '@/hooks/use-created-rows';
import { useSticky } from '@/hooks/use-sticky';
import { pct, relativeTime, shortId } from '@/lib/format';
import type { Agent } from '@/lib/types/domain';
import type { EvalCase, EvalCaseInput, EvalRunRow } from '@/lib/types/evals';

type CaseRow = EvalCase & { rowTestId: string };
type RunRow = EvalRunRow & { onRowClick: (r: EvalRunRow) => void; rowTestId: string };
type RunFilters = { trigger?: string[] };

function caseColumns(onDelete: ((c: EvalCase) => void) | null): ColumnDef<CaseRow>[] {
  return [
    ...(onDelete ? [selectColumn<CaseRow>((c) => c.name)] : []),
    {
      id: 'name',
      accessorFn: (c) => `${c.name} ${c.input}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Case" />,
      cell: ({ row }) => (
        <div className="max-w-80 min-w-56">
          <div className="flex items-center gap-1.5 font-medium">
            <span className="truncate">{row.original.name}</span>
            {row.original.status === 'draft' && (
              <Badge variant="outline" className="font-normal">
                Draft, not run
              </Badge>
            )}
          </div>
          <div className="truncate text-xs text-muted-foreground">{row.original.input}</div>
        </div>
      ),
      enableHiding: false,
    },
    {
      id: 'context',
      header: 'Knowledge',
      cell: ({ row }) => <div className="text-xs text-muted-foreground"><ListCell values={row.original.collections} empty="The agent’s own" label="Collections" className="max-w-48" /></div>,
    },
    { id: 'checks', header: 'Checks', cell: ({ row }) => <CheckChips checks={row.original.checks} max={2} /> },
    {
      accessorKey: 'source',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Source" />,
      cell: ({ row }) => <span className="text-xs text-muted-foreground">{SOURCE_LABEL[row.original.source] ?? row.original.source}</span>,
    },
    {
      accessorKey: 'createdAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Added" />,
      cell: ({ row }) => <span className="whitespace-nowrap text-xs text-muted-foreground">{relativeTime(row.original.createdAt)}</span>,
    },
    ...(onDelete
      ? [
          {
            id: 'actions',
            meta: { className: 'w-10' },
            cell: ({ row }) => (
              <StopRowClick>
                <Button variant="ghost" size="icon" aria-label={`Delete ${row.original.name}`} onClick={() => onDelete(row.original)}>
                  <Trash2 className="size-4" />
                </Button>
              </StopRowClick>
            ),
            enableHiding: false,
          } satisfies ColumnDef<CaseRow>,
        ]
      : []),
  ];
}

const runColumns: ColumnDef<RunRow>[] = [
  {
    id: 'id',
    accessorFn: (r) => r.id,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Run" />,
    cell: ({ row }) => (
      <div className="min-w-44">
        <div className="font-medium">{versionsLabel(row.original)}</div>
        <div className="font-mono text-xs text-muted-foreground" title={row.original.id}>
          {shortId(row.original.id)}
        </div>
      </div>
    ),
    enableHiding: false,
  },
  {
    accessorKey: 'trigger',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Started by" />,
    cell: ({ row }) => (
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {triggerLabel(row.original.trigger)} · {row.original.startedBy}
      </span>
    ),
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    id: 'passRate',
    header: 'Pass rate',
    cell: ({ row }) => {
      const s = row.original.summary;
      return (
        <span className="tabular-nums">
          {s.total ? pct(s.passed / s.total) : '—'} <span className="text-xs text-muted-foreground">({s.passed}/{s.total})</span>
        </span>
      );
    },
  },
  {
    id: 'regressions',
    header: 'Regressions',
    cell: ({ row }) => <span className={row.original.summary.regressions ? 'font-medium text-destructive-text tabular-nums' : 'tabular-nums text-muted-foreground'}>{row.original.summary.regressions}</span>,
  },
  { id: 'cost', header: 'Cost', cell: ({ row }) => <span className="tabular-nums">{costLabel(row.original)}</span> },
  {
    accessorKey: 'ranAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Ran" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-xs text-muted-foreground">{relativeTime(row.original.ranAt)}</span>,
  },
];

/** The table's columns the server sorts by, each with its `sortBy` value. */
const RUN_SORT = { trigger: 'trigger', ranAt: 'ranAt' };

/**
 * The agent's Evals tab: the saved cases and the kept runs as two views of one table, and the newest run above them.
 * A run happens when someone presses Run evals or runs `opsai agents eval`; it answers when it has finished.
 */
export function EvalsTab({ agent }: { agent: Agent }) {
  const mayRun = useCan('evals', 'run') === true;
  const latest = useLatestEvalRun(agent.id);
  const cases = useEvalCases(agent.id);
  const grantable = useGrantableTools();
  const runEvals = useRunEvals(agent.id);
  const addCases = useAddEvalCases(agent.id);
  const createdCases = useCreatedRows<CaseRow>();
  const remove = useDeleteEvalCase(agent.id);
  const bulkRemove = useBulkDeleteEvalCases(agent.id);

  const runList = useListParams<RunFilters>('id', 10, undefined, RUN_SORT);
  const runs = useEvalRuns(agent.id, runList.params);

  const [view, setView] = React.useState<'cases' | 'runs'>('cases');
  const [addOpen, setAddOpen] = React.useState(false);
  // A success check from the agent's brief, offered as the rubric of a new case; the brief no longer shows them.
  const [seed, setSeed] = React.useState<Partial<EvalCaseInput> | undefined>();
  const successChecks = agent.brief?.success ?? [];
  const openAdd = (from?: string) => (setSeed(from ? { name: from, checks: [{ type: 'judge', rubric: from }] } : undefined), setAddOpen(true));
  const [importOpen, setImportOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<EvalCase | null>(null);
  const [bulkDeleting, setBulkDeleting] = React.useState<EvalCase[] | null>(null);
  const shownBulk = useSticky(bulkDeleting);
  const [resetKey, setResetKey] = React.useState(0);
  const [openRunId, setOpenRunId] = React.useState<string | null>(null);
  const openRun = useEvalRun(openRunId);

  // The agent's own tools, by the name a calls_tool check matches on.
  const toolNames = React.useMemo(() => (grantable.data ?? []).filter((t) => agent.toolIds.includes(t.id)).map((t) => t.name), [grantable.data, agent.toolIds]);
  const caseRows: CaseRow[] = React.useMemo(() => (cases.data ?? []).map((c) => ({ ...c, rowTestId: `eval-case-${c.id}` })), [cases.data]);
  const caseCols = React.useMemo(() => caseColumns(mayRun ? setDeleting : null), [mayRun]);
  const runRows: RunRow[] = React.useMemo(() => (runs.data?.data ?? []).map((r) => ({ ...r, onRowClick: (x: EvalRunRow) => setOpenRunId(x.id), rowTestId: `eval-run-${r.id}` })), [runs.data]);
  const runIndex = runRows.findIndex((r) => r.id === openRunId);
  const runFacets = runs.data?.facets ?? {};
  const hasCases = (cases.data?.length ?? 0) > 0;

  /** Adds cases and pins the ones the answer holds that were not there before, so they show whatever the table's search says. */
  const save = async (input: EvalCaseInput[]) => {
    const before = new Set((cases.data ?? []).map((c) => c.id));
    const saved = await addCases.mutateAsync(input);
    saved.filter((c) => !before.has(c.id)).forEach((c) => createdCases.show({ ...c, rowTestId: `eval-case-${c.id}` }));
  };

  const start = () =>
    runEvals.mutate(undefined, {
      onSuccess: (r) => toast.success(`Ran ${versionsLabel(r)}: ${r.summary.passed} of ${r.summary.total} passed`, { description: `Cost ${costLabel(r)}.` }),
      onError: (e) => toast.error('Evals could not run', { description: e.message }),
    });

  return (
    <div className="flex flex-col gap-6" data-testid="agent-evals-tab">
      <Section
        title="Latest run"
        description="Runs the saved cases on the newest version, and on the live one when that is another. A run happens when someone presses Run evals or runs opsai agents eval."
        bodyClassName="flex flex-col gap-3 p-4"
        actions={
          mayRun && (
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
                <Upload className="size-3.5" /> Import CSV
              </Button>
              <Button variant="outline" size="sm" onClick={() => openAdd()} data-testid="add-eval-case-button">
                <Plus className="size-3.5" /> Add case
              </Button>
              <LoadingButton size="sm" isLoading={runEvals.isPending} loadingText="Running…" disabled={!hasCases} onClick={start} data-testid="run-evals-button">
                <Play className="size-3.5" /> Run evals
              </LoadingButton>
            </div>
          )
        }
      >
        {latest.isPending || cases.isPending ? (
          <Skeleton className="h-40 w-full rounded-lg" />
        ) : latest.isError ? (
          <QueryError what="the latest eval run" onRetry={() => latest.refetch()} error={latest.error} retrying={latest.isFetching} />
        ) : !latest.data ? (
          <EmptyState
            icon={FlaskConical}
            title={hasCases ? 'No eval runs yet' : 'No saved cases yet'}
            description={hasCases ? 'Run evals to test this agent against its saved cases.' : 'Add the cases this agent must keep getting right, then run them.'}
            action={mayRun ? (hasCases ? { label: 'Run evals', onClick: start } : { label: 'Add case', onClick: () => openAdd() }) : undefined}
          />
        ) : (
          <>
            <div className="text-xs text-muted-foreground">
              <span className="font-mono" title={latest.data.id}>
                {shortId(latest.data.id)}
              </span>{' '}
              · {versionsLabel(latest.data)} · {triggerLabel(latest.data.trigger)} by {latest.data.startedBy} · {relativeTime(latest.data.ranAt)}
            </div>
            <EvalRunSummary run={latest.data} />
            <EvalResultsTable results={latest.data.results} liveVersion={latest.data.liveVersion} />
          </>
        )}
      </Section>

      {mayRun && successChecks.length > 0 && (
        <Section title="Success checks from the brief" description="Written on an earlier version of the brief. Make each a case so a run grades it." flush>
          <Rows testId="eval-success-checks">
            {successChecks.map((check) => (
              <Row
                key={check}
                wrap
                title={check}
                trailing={
                  <Button variant="outline" size="sm" onClick={() => openAdd(check)}>
                    <Plus className="size-3.5" /> Make case
                  </Button>
                }
              />
            ))}
          </Rows>
        </Section>
      )}

      {(hasCases || !!latest.data) && (
        <section className="flex flex-col gap-3">
          <ToggleGroup type="single" variant="outline" size="sm" value={view} onValueChange={(v) => v && setView(v as 'cases' | 'runs')} className="self-start" aria-label="Saved cases or kept runs">
            <ToggleGroupItem value="cases" data-testid="evals-view-cases">
              Cases
            </ToggleGroupItem>
            <ToggleGroupItem value="runs" data-testid="evals-view-runs">
              Runs
            </ToggleGroupItem>
          </ToggleGroup>
          {view === 'cases' ? (
            cases.isError && !cases.data ? (
              <QueryError what="eval cases" onRetry={() => cases.refetch()} error={cases.error} retrying={cases.isFetching} />
            ) : (
              <DataTableWithViews
                key="cases"
                columns={caseCols}
                data={caseRows}
                getRowId={(r) => r.id}
                created={createdCases}
                searchColumn="name"
                searchPlaceholder="Search cases…"
                selectionResetKey={resetKey}
                bulkActions={mayRun ? [{ label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (rows) => setBulkDeleting(rows) }] : undefined}
                rowNoun="case"
                emptyState={<ListEmpty icon={FlaskConical} noun="eval cases" filtered={false} description="Add the cases this agent must keep getting right." createLabel={mayRun ? 'Add case' : undefined} onCreate={mayRun ? () => openAdd() : undefined} />}
              />
            )
          ) : runs.isPending ? (
            <Skeleton className="h-40 w-full" />
          ) : runs.isError && !runs.data ? (
            <QueryError what="eval run history" onRetry={() => runs.refetch()} error={runs.error} retrying={runs.isFetching} />
          ) : (
            <DataTableWithViews
              key="runs"
              columns={runColumns}
              data={runRows}
              getRowId={(r) => r.id}
              searchColumn="id"
              searchPlaceholder="Search runs…"
              filters={[{ column: 'trigger', title: 'Started by', options: (['manual', 'cli', 'publish_request'] as const).map((v) => ({ value: v, label: triggerLabel(v), count: runFacets.trigger?.[v] ?? 0 })) }]}
              onColumnFiltersChange={runList.onColumnFiltersChange}
              serverPagination={serverPagination(runList, runs)}
              serverSorting={runList.serverSort}
              emptyState={<ListEmpty icon={FlaskConical} noun="eval runs" filtered={runList.isFiltered} description="Runs appear here each time someone runs evals." />}
            />
          )}
        </section>
      )}

      <DetailSheet
        open={!!openRunId}
        onOpenChange={(o) => !o && setOpenRunId(null)}
        title={openRun.data ? `Eval run · ${versionsLabel(openRun.data)}` : 'Eval run'}
        description={openRun.data ? `${openRun.data.id} · ${triggerLabel(openRun.data.trigger)} by ${openRun.data.startedBy} · ${relativeTime(openRun.data.ranAt)}` : undefined}
        navigation={
          openRunId && runIndex >= 0
            ? {
                currentIndex: runIndex + (runList.pagination.page - 1) * runList.pagination.pageSize,
                totalCount: runs.data?.pagination.total ?? runRows.length,
                onPrev: runIndex > 0 ? () => setOpenRunId(runRows[runIndex - 1].id) : undefined,
                onNext: runIndex < runRows.length - 1 ? () => setOpenRunId(runRows[runIndex + 1].id) : undefined,
              }
            : undefined
        }
        scrollKey={openRunId ?? undefined}
        testId="eval-run-sheet"
      >
        {openRun.isPending ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        ) : openRun.isError ? (
          <QueryError what="this eval run" onRetry={() => openRun.refetch()} error={openRun.error} retrying={openRun.isFetching} />
        ) : (
          <div className="flex flex-col gap-4">
            <EvalRunSummary run={openRun.data} />
            <EvalResultsTable results={openRun.data.results} liveVersion={openRun.data.liveVersion} />
          </div>
        )}
      </DetailSheet>

      <EvalCaseDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        tools={toolNames}
        collections={agent.collections}
        seed={seed}
        isPending={addCases.isPending}
        onSubmit={async (i) => {
          await save([i]);
          toast.success(`Added ${i.name}`, { description: 'It runs the next time someone runs evals.' });
        }}
      />
      <ImportEvalCasesDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        collections={agent.collections}
        tools={toolNames}
        isPending={addCases.isPending}
        onImport={async (rows) => {
          await save(rows);
          toast.success(`Imported ${rows.length} ${rows.length === 1 ? 'case' : 'cases'}`);
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="eval case"
        entityName={deleting?.name}
        description={`“${deleting?.name}” stops running. Past runs keep its results.`}
        isLoading={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await remove.mutateAsync(deleting.id);
            toast.success(`Deleted ${deleting.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error('Couldn’t delete the case', { description: (e as Error).message });
          }
        }}
      />
      <DeleteDialog
        open={!!bulkDeleting}
        onOpenChange={(o) => !o && setBulkDeleting(null)}
        entityType="eval case"
        count={shownBulk?.length ?? 0}
        description="They stop running. Past runs keep their results."
        isLoading={bulkRemove.isPending}
        onConfirm={async () => {
          const rows = bulkDeleting ?? [];
          const res = await bulkRemove.mutateAsync(rows.map((c) => c.id));
          toastBulk(res, 'Deleted', 'eval case', (id) => rows.find((c) => c.id === id)?.name ?? id);
          setBulkDeleting(null);
          setResetKey((k) => k + 1);
        }}
      >
        <SelectedList names={(shownBulk ?? []).map((c) => c.name)} />
      </DeleteDialog>
    </div>
  );
}
