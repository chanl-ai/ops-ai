'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { FlaskConical, History, Lock, Play, Plus, Trash2, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { EvalCaseDialog } from '@/components/evals/eval-case-dialog';
import { CheckChips, OutcomeText, SOURCE_LABEL, SUITE_LABEL } from '@/components/evals/eval-meta';
import { EvalResultsTable, EvalRunSummary, EvalSuiteGrid, TRIGGER_LABEL, versionsLabel } from '@/components/evals/eval-results';
import { ImportEvalCasesDialog } from '@/components/evals/import-eval-cases-dialog';
import { SelectedList, toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { EmptyState } from '@/components/shared/empty-state';
import { FieldSectionLabel } from '@/components/shared/field-row';
import { StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useBulkDeleteEvalCases, useCreateEvalCase, useDeleteEvalCase, useEvalCases, useEvalOptions, useEvalRun, useEvalRuns, useEvalSuites, useImportEvalCases, useLatestEvalRun, useRunEvals } from '@/hooks/eval-queries';
import { useRunAsPrincipals } from '@/hooks/run-as-queries';
import { useSticky } from '@/hooks/use-sticky';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import { pct, relativeTime, shortId } from '@/lib/format';
import type { Agent } from '@/lib/types/domain';
import type { EvalCase, EvalCaseFilters, EvalRunFilters, EvalRunRow } from '@/lib/types/evals';

type CaseRow = EvalCase & { rowTestId: string };
type RunRow = EvalRunRow & { onRowClick: (r: EvalRunRow) => void; rowTestId: string };

const SUITE_OPTIONS = (['agent', 'injection', 'leakage', 'refusals'] as const).map((v) => ({ value: v, label: SUITE_LABEL[v] }));
const SOURCE_OPTIONS = ['manual', 'csv', 'test_turn', 'platform'].map((v) => ({ value: v, label: SOURCE_LABEL[v] }));
const OUTCOME_OPTIONS = [
  { value: 'pass', label: 'Passed' },
  { value: 'fail', label: 'Failed' },
  { value: 'not_run', label: 'Not run' },
];

function caseColumns(onDelete: (c: EvalCase) => void): ColumnDef<CaseRow>[] {
  return [
    selectColumn<CaseRow>((c) => c.name, (c) => !c.readOnly),
    {
      id: 'name',
      accessorFn: (c) => `${c.name} ${c.input}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Case" />,
      cell: ({ row }) => (
        <div className="max-w-80 min-w-56">
          <div className="flex items-center gap-1.5 font-medium">
            {row.original.readOnly && <Lock className="size-3 shrink-0 text-muted-foreground" aria-label="Platform case, read-only" />}
            <span className="truncate">{row.original.name}</span>
          </div>
          <div className="truncate text-xs text-muted-foreground">{row.original.input}</div>
        </div>
      ),
      enableHiding: false,
    },
    {
      accessorKey: 'suite',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Suite" />,
      cell: ({ row }) => <span className="whitespace-nowrap text-xs text-muted-foreground">{SUITE_LABEL[row.original.suite]}</span>,
      filterFn: facetFilterFn,
      enableSorting: false,
    },
    {
      id: 'context',
      header: 'Runs as',
      cell: ({ row }) => (
        <div className="max-w-48 text-xs">
          <div className="truncate">{row.original.context.runAsName ?? 'Agent’s own access'}</div>
          {row.original.context.collections.length > 0 && <div className="truncate text-muted-foreground">{row.original.context.collections.join(', ')}</div>}
        </div>
      ),
    },
    { id: 'checks', header: 'Checks', cell: ({ row }) => <CheckChips checks={row.original.checks} max={2} /> },
    {
      accessorKey: 'source',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Source" />,
      cell: ({ row }) => <span className="text-xs text-muted-foreground">{SOURCE_LABEL[row.original.source]}</span>,
      filterFn: facetFilterFn,
      enableSorting: false,
    },
    {
      id: 'lastOutcome',
      accessorFn: (c) => c.lastOutcome ?? 'not_run',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Latest result" />,
      cell: ({ row }) => <OutcomeText status={row.original.lastOutcome} />,
      filterFn: facetFilterFn,
    },
    {
      id: 'actions',
      meta: { className: 'w-10' },
      cell: ({ row }) =>
        row.original.readOnly ? null : (
          <StopRowClick>
            <Button variant="ghost" size="icon" className="size-8" aria-label={`Delete ${row.original.name}`} onClick={() => onDelete(row.original)}>
              <Trash2 className="size-4" />
            </Button>
          </StopRowClick>
        ),
      enableHiding: false,
    },
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
        {TRIGGER_LABEL[row.original.trigger]} · {row.original.requestedBy}
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
      return s ? (
        <span className="tabular-nums">
          {pct(s.passed / Math.max(1, s.total))} <span className="text-xs text-muted-foreground">({s.passed}/{s.total})</span>
        </span>
      ) : (
        <Badge variant="secondary">Running</Badge>
      );
    },
  },
  {
    id: 'regressions',
    header: 'Regressions',
    cell: ({ row }) => {
      const n = row.original.summary?.regressions;
      return n === undefined ? '—' : <span className={n ? 'font-medium text-red-600 tabular-nums dark:text-red-400' : 'tabular-nums text-muted-foreground'}>{n}</span>;
    },
  },
  {
    id: 'injection',
    header: 'Injection',
    cell: ({ row }) => {
      const s = row.original.summary?.suites.find((x) => x.kind === 'injection');
      return s ? <span className={s.passed < s.total ? 'text-red-600 tabular-nums dark:text-red-400' : 'tabular-nums'}>{s.passed}/{s.total}</span> : '—';
    },
  },
  {
    accessorKey: 'status',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />,
    cell: ({ row }) => <Badge variant={row.original.status === 'running' ? 'secondary' : 'outline'}>{row.original.status === 'running' ? 'Running' : 'Complete'}</Badge>,
    filterFn: facetFilterFn,
    enableSorting: false,
  },
  {
    accessorKey: 'startedAt',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Started" />,
    cell: ({ row }) => <span className="whitespace-nowrap text-xs text-muted-foreground">{relativeTime(row.original.startedAt)}</span>,
  },
];

/**
 * The agent's Evals tab: latest run, suites, the test set and run history. Every save of the agent starts a
 * run on its own, so the latest run updates without anyone pressing Run.
 */
export function EvalsTab({ agent }: { agent: Agent }) {
  const latest = useLatestEvalRun(agent.id);
  const suites = useEvalSuites(agent.id);
  const options = useEvalOptions(agent.id);
  const principals = useRunAsPrincipals();
  const runEvals = useRunEvals(agent.id);
  const create = useCreateEvalCase(agent.id);
  const importRows = useImportEvalCases(agent.id);
  const remove = useDeleteEvalCase(agent.id);
  const bulkRemove = useBulkDeleteEvalCases(agent.id);

  const caseList = useListParams<EvalCaseFilters>('name');
  const cases = useEvalCases(agent.id, caseList.params);
  const runList = useListParams<EvalRunFilters>('id', 10);
  const runs = useEvalRuns(agent.id, runList.params);

  const [addOpen, setAddOpen] = React.useState(false);
  const [importOpen, setImportOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<EvalCase | null>(null);
  const [bulkDeleting, setBulkDeleting] = React.useState<EvalCase[] | null>(null);
  const shownBulk = useSticky(bulkDeleting);
  const [resetKey, setResetKey] = React.useState(0);
  const [openRunId, setOpenRunId] = React.useState<string | null>(null);
  const openRun = useEvalRun(openRunId);

  const caseRows: CaseRow[] = React.useMemo(() => (cases.data?.data ?? []).map((c) => ({ ...c, rowTestId: `eval-case-${c.id}` })), [cases.data]);
  const caseCols = React.useMemo(() => caseColumns(setDeleting), []);
  const runRows: RunRow[] = React.useMemo(() => (runs.data?.data ?? []).map((r) => ({ ...r, onRowClick: (x: EvalRunRow) => setOpenRunId(x.id), rowTestId: `eval-run-${r.id}` })), [runs.data]);
  const runIndex = runRows.findIndex((r) => r.id === openRunId);
  const facets = cases.data?.facets ?? {};
  const runFacets = runs.data?.facets ?? {};
  const running = latest.data?.status === 'running';

  const start = () =>
    runEvals.mutate(undefined, {
      onSuccess: (r) => toast.success(`Running evals on ${versionsLabel(r)}`, { description: 'Results appear here in a few seconds.' }),
      onError: (e) => toast.error('Evals could not start', { description: e.message }),
    });

  return (
    <div className="flex flex-col gap-6" data-testid="agent-evals-tab">
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-0">
            <h2 className="text-base font-semibold">Latest run</h2>
            <p className="text-sm text-muted-foreground">Tests the newest version against the version live workflows use. Saving the agent starts a run.</p>
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
              <Upload className="size-3.5" /> Import CSV
            </Button>
            <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>
              <Plus className="size-3.5" /> Add case
            </Button>
            <LoadingButton size="sm" isLoading={runEvals.isPending || running} loadingText={running ? 'Running…' : 'Starting…'} onClick={start} data-testid="run-evals-button">
              <Play className="size-3.5" /> Run evals
            </LoadingButton>
          </div>
        </div>
        {latest.isPending ? (
          <Skeleton className="h-40 w-full rounded-lg" />
        ) : latest.isError ? (
          <QueryError what="the latest eval run" onRetry={() => latest.refetch()} retrying={latest.isFetching} />
        ) : !latest.data ? (
          <EmptyState icon={FlaskConical} title="No eval runs yet" description="Run evals to test this agent against its test set and the platform's injection, leakage and refusal sets." action={{ label: 'Run evals', onClick: start }} />
        ) : (
          <>
            <div className="text-xs text-muted-foreground">
              <span className="font-mono" title={latest.data.id}>
                {shortId(latest.data.id)}
              </span>{' '}
              · {TRIGGER_LABEL[latest.data.trigger]} by {latest.data.requestedBy} · {relativeTime(latest.data.startedAt)}
            </div>
            <EvalRunSummary run={latest.data} />
            {latest.data.status === 'complete' && <EvalResultsTable results={latest.data.results} compared={latest.data.compared} />}
          </>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <FieldSectionLabel className="px-0">Suites</FieldSectionLabel>
        {suites.isPending ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-32 rounded-lg" />
            ))}
          </div>
        ) : suites.isError ? (
          <QueryError what="eval suites" onRetry={() => suites.refetch()} retrying={suites.isFetching} />
        ) : (
          <EvalSuiteGrid suites={suites.data} />
        )}
      </section>

      <section className="flex flex-col">
        <FieldSectionLabel className="px-0">Test set</FieldSectionLabel>
        <p className="text-sm text-muted-foreground">Platform cases are attached to every agent and maintained by the platform team; they cannot be edited or deleted here.</p>
        {cases.isPending ? (
          <div className="mt-4 flex flex-col gap-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : cases.isError && !cases.data ? (
          <QueryError what="eval cases" onRetry={() => cases.refetch()} retrying={cases.isFetching} />
        ) : (
          <DataTableWithViews
            columns={caseCols}
            data={caseRows}
            getRowId={(r) => r.id}
            searchColumn="name"
            searchPlaceholder="Search cases…"
            filters={[
              { column: 'suite', title: 'Suite', options: SUITE_OPTIONS.map((o) => ({ ...o, count: facets.suite?.[o.value] ?? 0 })) },
              { column: 'source', title: 'Source', options: SOURCE_OPTIONS.map((o) => ({ ...o, count: facets.source?.[o.value] ?? 0 })) },
              { column: 'lastOutcome', title: 'Latest result', options: OUTCOME_OPTIONS.map((o) => ({ ...o, count: facets.lastOutcome?.[o.value] ?? 0 })) },
            ]}
            onColumnFiltersChange={caseList.onColumnFiltersChange}
            selectionResetKey={resetKey}
            bulkActions={[{ label: 'Delete', icon: Trash2, variant: 'destructive', onClick: (rows) => setBulkDeleting(rows) }]}
            serverPagination={{
              enabled: true,
              total: cases.data?.pagination.total ?? 0,
              page: caseList.pagination.page,
              pageSize: caseList.pagination.pageSize,
              totalPages: cases.data?.pagination.totalPages,
              onPaginationChange: caseList.setPagination,
              isLoading: cases.isFetching && cases.isPlaceholderData,
            }}
            emptyState={<ListEmpty icon={FlaskConical} noun="eval cases" filtered={caseList.isFiltered} description="Add the cases this agent must keep getting right." createLabel="Add case" onCreate={() => setAddOpen(true)} />}
          />
        )}
      </section>

      <section className="flex flex-col">
        <FieldSectionLabel className="px-0">Run history</FieldSectionLabel>
        {runs.isPending ? (
          <Skeleton className="mt-4 h-40 w-full" />
        ) : runs.isError && !runs.data ? (
          <QueryError what="eval run history" onRetry={() => runs.refetch()} retrying={runs.isFetching} />
        ) : (
          <DataTableWithViews
            columns={runColumns}
            data={runRows}
            getRowId={(r) => r.id}
            searchColumn="id"
            searchPlaceholder="Search runs…"
            filters={[
              { column: 'trigger', title: 'Started by', options: (['save', 'manual', 'restore'] as const).map((v) => ({ value: v, label: TRIGGER_LABEL[v], count: runFacets.trigger?.[v] ?? 0 })) },
              { column: 'status', title: 'Status', options: [{ value: 'running', label: 'Running', count: runFacets.status?.running ?? 0 }, { value: 'complete', label: 'Complete', count: runFacets.status?.complete ?? 0 }] },
            ]}
            onColumnFiltersChange={runList.onColumnFiltersChange}
            serverPagination={{
              enabled: true,
              total: runs.data?.pagination.total ?? 0,
              page: runList.pagination.page,
              pageSize: runList.pagination.pageSize,
              totalPages: runs.data?.pagination.totalPages,
              onPaginationChange: runList.setPagination,
              isLoading: runs.isFetching && runs.isPlaceholderData,
            }}
            emptyState={<ListEmpty icon={History} noun="eval runs" filtered={runList.isFiltered} description="Runs appear here after each save and each time someone runs evals." />}
          />
        )}
      </section>

      <DetailSheet
        open={!!openRunId}
        onOpenChange={(o) => !o && setOpenRunId(null)}
        title={openRun.data ? `Eval run · ${versionsLabel(openRun.data)}` : 'Eval run'}
        description={openRun.data ? `${openRun.data.id} · ${TRIGGER_LABEL[openRun.data.trigger]} by ${openRun.data.requestedBy} · ${relativeTime(openRun.data.startedAt)}` : undefined}
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
          <QueryError what="this eval run" onRetry={() => openRun.refetch()} retrying={openRun.isFetching} />
        ) : (
          <div className="flex flex-col gap-4">
            <EvalRunSummary run={openRun.data} />
            {openRun.data.status === 'complete' && <EvalResultsTable results={openRun.data.results} compared={openRun.data.compared} />}
          </div>
        )}
      </DetailSheet>

      <EvalCaseDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        principals={principals.data ?? []}
        options={options.data}
        isPending={create.isPending}
        onSubmit={async (i) => {
          await create.mutateAsync(i);
          toast.success(`Added ${i.name}`, { description: 'It runs on the next save or when you run evals.' });
        }}
      />
      <ImportEvalCasesDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        principals={principals.data ?? []}
        collections={options.data?.collections ?? []}
        tools={options.data?.tools ?? []}
        isPending={importRows.isPending}
        onImport={async (rows) => {
          const res = await importRows.mutateAsync(rows);
          toastBulk(res, 'Imported', 'eval case', (i) => rows[Number(i)]?.name || `Row ${Number(i) + 2}`);
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="eval case"
        entityName={deleting?.name}
        description={`“${deleting?.name}” stops running on saves and eval runs. Past runs keep its results.`}
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
        description="They stop running on saves and eval runs. Platform cases are skipped."
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
