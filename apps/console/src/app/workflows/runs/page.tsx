'use client';

import * as React from 'react';
import { CheckCircle2, Clock, Inbox, Mail, UserCheck, Users } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { RUN_STATE_OPTIONS, runColumns, RunSummary, type RunTableRow } from '@/components/cases/run-columns';
import { RunStateDetail } from '@/components/cases/run-state';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { RunnerRuns } from '@/components/workflows/runner-runs';
import { RunSheet } from '@/components/workflows/run-sheet';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAssignRuns, useCaseQueues, useCaseRun, useCaseRuns, useRunState } from '@/hooks/case-queries';
import { useTestFromRun, useWorkflows } from '@/hooks/queries';
import { useListParams } from '@/hooks/use-list-params';
import { useSticky } from '@/hooks/use-sticky';
import type { RunRow, RunRowFilters, RunView } from '@/lib/types/cases';

const EMPTY_COPY: Record<RunView, { noun: string; description: string }> = {
  needs_person: { noun: 'runs waiting on a person', description: 'No run is paused for a reviewer or an approval right now.' },
  open: { noun: 'open runs', description: 'Runs appear here while a workflow is working on them.' },
  past_sla: { noun: 'runs past SLA', description: 'Every open run is inside its SLA.' },
  done_today: { noun: 'runs finished today', description: 'Runs that finish today appear here.' },
};

/**
 * Workflows › Runs: every workflow's runs, what waits on a person, and their SLA (moved from Cases by c-220). The two
 * kinds of workflow keep separate lists, each from its own service list: Runner · v2 (built on the canvas, agents-service
 * `/v1/runs`) first, and Graph · v1 (the runs service), which a `?run=` or `?parent=` link to one of its runs opens.
 */
export default function RunsPage() {
  const router = useRouter();
  const search = useSearchParams();
  const [view, setView] = React.useState<RunView>('needs_person');
  const list = useListParams<RunRowFilters>('subject');
  const query = useCaseRuns({ ...list.params, view });
  const { data: queues } = useCaseQueues();
  const { data: workflows } = useWorkflows({ page: 1, pageSize: 100 });
  const assign = useAssignRuns();
  const saveAsTest = useTestFromRun();
  const [bulk, setBulk] = React.useState<RunRow[] | null>(null);
  const shown = useSticky(bulk);
  const [selectionResetKey, setSelectionResetKey] = React.useState(0);

  // `?run=` opens one run's sheet; links from the Overview and old case links use it. `?parent=` lists the runs one
  // run opened (the API's parent filter), from a parent's sheet.
  const activeId = search.get('run');
  // A runner run (wfrun_…) has its own page with its graph and steps; a link naming one opens that page, not the sheet.
  React.useEffect(() => {
    if (activeId?.startsWith('wfrun_')) router.replace(`/workflows/runs/${encodeURIComponent(activeId)}`);
  }, [activeId, router]);
  const parent = search.get('parent');
  const kind = search.get('kind') === 'graph' || (activeId && !activeId.startsWith('wfrun_')) || parent ? 'graph' : 'runner';
  const kindTabs = (
    <Tabs value={kind} onValueChange={(k) => router.replace(k === 'graph' ? '/workflows/runs?kind=graph' : '/workflows/runs', { scroll: false })}>
      <TabsList aria-label="Kind of workflow">
        <TabsTrigger value="runner" data-testid="runs-kind-runner">
          Runner · v2
        </TabsTrigger>
        <TabsTrigger value="graph" data-testid="runs-kind-graph">
          Graph · v1
        </TabsTrigger>
      </TabsList>
    </Tabs>
  );
  const setActiveId = React.useCallback(
    (id: string | null) => {
      const p = new URLSearchParams(search.toString());
      if (id) p.set('run', id);
      else {
        // Closing a graph run's sheet stays on the Graph tab, which the run id alone was choosing.
        if (p.get('run') && !p.get('run')!.startsWith('wfrun_')) p.set('kind', 'graph');
        p.delete('run');
      }
      router.replace(`/workflows/runs${p.size ? `?${p}` : ''}`, { scroll: false });
    },
    [router, search],
  );

  const rows = React.useMemo(() => query.data?.data ?? [], [query.data]);
  const idx = rows.findIndex((r) => r.id === activeId);
  const linked = useCaseRun(idx < 0 && !activeId?.startsWith('wfrun_') ? activeId : null);
  const active = idx >= 0 ? rows[idx] : (linked.data ?? null);
  // The row says how the run stands; its state says what the workflow read and wrote, drawn as widget parts.
  const runState = useRunState(active?.id ?? null);
  const tableRows: RunTableRow[] = React.useMemo(() => rows.map((r) => ({ ...r, onRowClick: (x: RunRow) => setActiveId(x.id), rowTestId: `run-row-${r.id}` })), [rows, setActiveId]);

  const counts = query.data?.viewCounts;
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, options: { label: string; value: string }[]) => options.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const workflowOptions = (workflows?.data ?? []).map((w) => ({ label: w.name, value: w.id }));
  const queueOptions = Object.keys(facets.queue ?? {}).map((q) => ({ label: q, value: q }));
  const resetSelection = () => setSelectionResetKey((k) => k + 1);
  const empty = EMPTY_COPY[view];

  return (
    <PageLayout icon={Mail} title="Runs" switcher description={parent ? `Runs opened by ${parent}: what is open, what waits on a person, and what the agent did` : 'Runs across every workflow: what is open, what waits on a person, and what the agent did'}>
      <div className="mb-4">{kindTabs}</div>
      {kind === 'runner' ? (
        <RunnerRuns />
      ) : query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="runs" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} testId="cases-error" />
      ) : (
        <div className="flex flex-col gap-4">
          <SavedViewTabs
            ariaLabel="Run views"
            presets={[
              { id: 'needs_person', label: `Needs a person · ${counts?.needs_person ?? 0}`, icon: UserCheck },
              { id: 'open', label: `Open · ${counts?.open ?? 0}`, icon: Inbox },
              { id: 'past_sla', label: `Past SLA · ${counts?.past_sla ?? 0}`, icon: Clock },
              { id: 'done_today', label: `Done today · ${counts?.done_today ?? 0}`, icon: CheckCircle2 },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as RunView);
              list.reset();
              resetSelection();
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />

          <DataTableWithViews
            columns={runColumns}
            data={tableRows}
            getRowId={(r) => r.id}
            searchColumn="subject"
            searchPlaceholder="Search subject, run or case id…"
            initialColumnFilters={parent ? [{ id: 'parent', value: [parent] }] : undefined}
            filters={[
              { column: 'workflowId', title: 'Workflow', options: withCounts('workflowId', workflowOptions) },
              { column: 'state', title: 'State', options: withCounts('state', RUN_STATE_OPTIONS) },
              { column: 'queue', title: 'Queue', options: withCounts('queue', queueOptions) },
            ]}
            onColumnFiltersChange={list.onColumnFiltersChange}
            selectionResetKey={selectionResetKey}
            serverPagination={{
              enabled: true,
              total: query.data?.pagination.total ?? 0,
              page: list.pagination.page,
              pageSize: list.pagination.pageSize,
              totalPages: query.data?.pagination.totalPages,
              onPaginationChange: list.setPagination,
              isLoading: query.isFetching && query.isPlaceholderData,
            }}
            bulkActions={view === 'done_today' ? [] : [{ label: 'Assign', icon: Users, variant: 'outline', onClick: (selected) => setBulk(selected) }]}
            emptyState={
              <ListEmpty
                icon={Mail}
                noun={empty.noun}
                filtered={list.isFiltered}
                createLabel={view === 'open' ? 'Go to workflows' : 'Show all open runs'}
                onCreate={() => {
                  if (view === 'open') router.push('/workflows');
                  else {
                    setView('open');
                    list.reset();
                    resetSelection();
                  }
                }}
                description={empty.description}
              />
            }
          />
        </div>
      )}

      <RunSheet
        run={active}
        onClose={() => setActiveId(null)}
        navigation={
          idx >= 0
            ? {
                currentIndex: idx,
                totalCount: rows.length,
                onPrev: idx > 0 ? () => setActiveId(rows[idx - 1].id) : undefined,
                onNext: idx < rows.length - 1 ? () => setActiveId(rows[idx + 1].id) : undefined,
              }
            : undefined
        }
        summary={
          active && (
            <>
              <RunSummary run={active} />
              <RunStateDetail runId={active.id} state={runState.data} children={active.children} isPending={runState.isPending} isError={runState.isError} onRetry={() => runState.refetch()} />
            </>
          )
        }
        saving={saveAsTest.isPending}
        onSaveAsTest={(r) =>
          saveAsTest.mutate(r.id, {
            onSuccess: (t) => toast.success('Saved as a test case', { description: `${t.name}. It runs on every publish request.` }),
            onError: (e) => toast.error('Couldn’t save the test case', { description: e.message }),
          })
        }
      />

      <BulkFieldDialog
        open={!!bulk}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Assign ${shown?.length ?? 0} runs`}
        description="Runs started by an email are assigned with their case. Runs paused at a review gate are assigned in Reviews. SLA clocks keep running."
        fieldLabel="Assignee"
        options={queues?.assignees ?? []}
        names={(shown ?? []).map((r) => `${r.id} · ${r.subject}`)}
        confirmLabel="Assign"
        isPending={assign.isPending}
        onConfirm={async (assignee) => {
          const res = await assign.mutateAsync({ ids: bulk!.map((r) => r.id), assignee });
          toastBulk(res, `Assigned to ${assignee}:`, 'run');
          resetSelection();
        }}
      />
    </PageLayout>
  );
}
