'use client';

import * as React from 'react';
import { AlertCircle, CheckCircle2, Clock, Inbox, Mail, UserCheck, Users } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { RUN_STATE_OPTIONS, runColumns, RunSummary, type RunTableRow } from '@/components/cases/run-columns';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { RunSheet } from '@/components/workflows/run-sheet';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useAssignRuns, useCaseQueues, useCaseRun, useCaseRuns } from '@/hooks/case-queries';
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

export default function CasesPage() {
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

  // `?run=` opens one run's sheet; links from the Overview and old case links use it.
  const activeId = search.get('run');
  const setActiveId = React.useCallback(
    (id: string | null) => {
      const p = new URLSearchParams(search.toString());
      if (id) p.set('run', id);
      else p.delete('run');
      router.replace(`/cases${p.size ? `?${p}` : ''}`, { scroll: false });
    },
    [router, search],
  );

  const rows = React.useMemo(() => query.data?.data ?? [], [query.data]);
  const idx = rows.findIndex((r) => r.id === activeId);
  const linked = useCaseRun(idx < 0 ? activeId : null);
  const active = idx >= 0 ? rows[idx] : (linked.data ?? null);
  const tableRows: RunTableRow[] = React.useMemo(() => rows.map((r) => ({ ...r, onRowClick: (x: RunRow) => setActiveId(x.id), rowTestId: `run-row-${r.id}` })), [rows, setActiveId]);

  const counts = query.data?.viewCounts;
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, options: { label: string; value: string }[]) => options.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));
  const workflowOptions = (workflows?.data ?? []).map((w) => ({ label: w.name, value: w.id }));
  const queueOptions = Object.keys(facets.queue ?? {}).map((q) => ({ label: q, value: q }));
  const resetSelection = () => setSelectionResetKey((k) => k + 1);
  const empty = EMPTY_COPY[view];

  return (
    <PageLayout icon={Mail} title="Cases" description="Runs across every workflow: what is open, what waits on a person, and what the agent did">
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="runs" onRetry={() => query.refetch()} retrying={query.isFetching} testId="cases-error" />
      ) : (
        <div className="flex flex-col gap-4">
          {query.isError && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription className="flex items-center justify-between gap-2">
                Refreshing runs failed. These are the last results that loaded.
                <Button size="sm" variant="outline" onClick={() => query.refetch()}>
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          )}

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
        summary={active && <RunSummary run={active} />}
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
