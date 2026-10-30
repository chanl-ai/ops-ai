'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowLeft, List, UserCheck } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { KindView } from '@/components/chat/widgets/kind-view';
import { PageLayout } from '@/components/page-layout';
import { DecisionPanel } from '@/components/reviews/decision-panel';
import { type ReadEdits, useReadConfirmations } from '@/components/reviews/document-read';
import { QueueDone, TaskQueue } from '@/components/reviews/task-queue';
import { useReviewDecider } from '@/components/reviews/use-review-decider';
import { useCollapsedSidebar } from '@/components/shared/collapsed-sidebar';
import { QueryError } from '@/components/shared/query-states';
import { countLabel, SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { taskView } from '@/components/tasks/task-regions';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAssignReviews, useLookups, useReview, useReviewByRunKey, useReviewPlace, useReviews } from '@/hooks/queries';
import { useCurrentPerson } from '@/hooks/auth-queries';
import { useTeam } from '@/hooks/use-team';
import { cn } from '@/lib/utils';
import type { Review } from '@/lib/types/domain';
import type { ReviewView } from '@/lib/types/query';

const VIEWS = ['open', 'mine', 'overdue'] as const satisfies readonly ReviewView[];
const PAGE = 50;

/**
 * Human Tasks as queue and task (c-460, layout A, owner 2026-10-23): the queue grouped by case on the left, the open
 * task's evidence beside a decision panel that keeps Decide in view. From 1280 px the queue and the task sit side by
 * side, below that they take turns; from 1024 px the evidence and the decision sit side by side, below that they take
 * turns behind an Evidence and Decide switch. The app's navigation folds while the page is open, so the document has
 * room. The open task is ?review= (and ?runKey= resolves to one), as every link into a task already reads it. Every
 * view as a table, with bulk decisions and export, is All tasks.
 */
export default function HumanTasksPage() {
  useCollapsedSidebar();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const view: ReviewView = (VIEWS as readonly string[]).includes(params.get('view') ?? '') ? (params.get('view') as ReviewView) : 'open';
  const activeId = params.get('review');
  const [pageSize, setPageSize] = React.useState(PAGE);
  const query = useReviews({ view, group: 'case', page: 1, pageSize });
  const rows = React.useMemo(() => query.data?.data ?? [], [query.data]);
  const counts = query.data?.viewCounts;

  const go = React.useCallback(
    (next: { review?: string | null; view?: ReviewView }) => {
      const q = new URLSearchParams(params.toString());
      q.delete('runKey');
      if (next.view) q.set('view', next.view);
      if (next.review === null) q.delete('review');
      else if (next.review) q.set('review', next.review);
      router.replace(`${pathname}?${q.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );
  // A service links to a system workflow's review by its run key before the run has a step (c-257).
  const byKey = useReviewByRunKey(activeId ? null : params.get('runKey'));
  React.useEffect(() => {
    if (byKey.data) go({ review: byKey.data.id });
  }, [byKey.data, go]);

  // The open task: the one the address names (on this page or not, decided or not), else the queue's first.
  const listed = rows.find((r) => r.id === activeId);
  const fetched = useReview(activeId && !listed ? activeId : null);
  const active: Review | null = listed ?? fetched.data ?? (!activeId && !params.get('runKey') ? (rows[0] ?? null) : null);
  const missing = (fetched.error as { status?: number } | null)?.status === 404;
  const place = useReviewPlace(active?.id ?? null, { view, group: 'case' });

  const [pane, setPane] = React.useState<'decide' | 'evidence'>('decide');
  const [showTask, setShowTask] = React.useState(!!activeId);
  const open = React.useCallback(
    (r: Review) => {
      go({ review: r.id });
      setShowTask(true);
    },
    [go],
  );

  const task = React.useMemo(() => (active ? taskView(active) : null), [active]);
  const [edits, setEdits] = React.useState<ReadEdits>({});
  React.useEffect(() => {
    setEdits({});
    setPane('decide');
  }, [active?.id]);
  const onEdit = React.useCallback((record: number, key: string, text: string) => setEdits((e) => ({ ...e, [record]: { ...e[record], [key]: text } })), []);
  const checks = useReadConfirmations(active?.id);
  const me = useCurrentPerson().ids;
  const { team } = useTeam();
  const { data: lookups } = useLookups();
  const assign = useAssignReviews();

  // After a decision, a reassign or a decision someone made first, the next task in the same case opens, then the next
  // case, as the service orders them.
  const moveOn = React.useCallback(() => go({ review: place.data?.next ?? null }), [go, place.data?.next]);
  const decider = useReviewDecider({
    active,
    edits,
    confirmed: checks.confirmed,
    onDone: moveOn,
    action: (r) => (r.caseId ? { label: 'Open case', onClick: () => router.push(`/cases/${r.caseId}`) } : undefined),
  });
  const reassign = async (to: string) => {
    if (!active) return;
    try {
      await assign.mutateAsync({ ids: [active.id], assignee: to });
    } catch (e) {
      toast.error('Couldn’t reassign the task', { description: (e as Error).message });
      return;
    }
    toast.success(`Reassigned to ${to}`, { description: `${active.title} is in ${to}’s Assigned to me.` });
    moveOn();
  };

  const twoPanes = !!task?.evidence.some((n) => n.type === 'viewer');
  const allTasks = (
    <Button variant="outline" asChild>
      <Link href="/reviews/all" data-testid="all-tasks">
        <List /> All tasks
      </Link>
    </Button>
  );

  return (
    <PageLayout icon={UserCheck} title="Human Tasks" description="What waits for a person, grouped by case, soonest due first" className="min-h-0 flex-1 pb-0" contentClassName="flex min-h-0 flex-1 flex-col gap-3" actions={allTasks}>
      {decider.stepUp.dialog}
      <SavedViewTabs
        ariaLabel="Human Tasks views"
        presets={[
          { id: 'open', label: countLabel('All open', counts?.open) },
          { id: 'mine', label: countLabel('Assigned to me', counts?.mine) },
          { id: 'overdue', label: countLabel('Past SLA', counts?.overdue) },
        ]}
        savedViews={[]}
        activePresetId={view}
        activeSavedViewId={null}
        onSelectPreset={(id) => {
          setPageSize(PAGE);
          go({ view: id as ReviewView, review: null });
        }}
        onSelectSavedView={() => undefined}
        onSaveView={() => undefined}
        onDeleteView={() => undefined}
        canSave={false}
      />
      {query.isError && !query.data ? (
        <QueryError what="Human Tasks" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} testId="reviews-error" />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-4 xl:flex-row xl:overflow-clip" data-testid="queue-and-task">
          <div className={cn('min-h-0 flex-col xl:flex xl:w-72 xl:shrink-0 xl:overflow-y-auto xl:pr-1', showTask ? 'hidden' : 'flex')}>
            <TaskQueue
              rows={rows}
              total={query.data?.pagination.total ?? rows.length}
              activeId={active?.id ?? null}
              loading={query.isPending}
              onOpen={open}
              onMore={() => setPageSize((n) => n + PAGE)}
              loadingMore={query.isFetching}
            />
          </div>
          <div className={cn('min-h-0 min-w-0 flex-1 flex-col gap-3 xl:flex', showTask ? 'flex' : 'hidden')}>
            <Button variant="ghost" size="sm" className="self-start xl:hidden" onClick={() => setShowTask(false)} data-testid="back-to-queue">
              <ArrowLeft /> Queue
            </Button>
            {!active ? (
              query.isPending || fetched.isLoading || byKey.isLoading ? (
                <Skeleton className="h-96 w-full rounded-lg" />
              ) : missing ? (
                <QueryError what="this task" onRetry={() => fetched.refetch()} error={fetched.error} retrying={fetched.isFetching} testId="task-error" />
              ) : (
                <QueueDone />
              )
            ) : (
              task && (
                <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
                  {twoPanes && (
                    <Tabs value={pane} onValueChange={(v) => setPane(v as 'decide' | 'evidence')} className="lg:hidden">
                      <TabsList className="w-full">
                        <TabsTrigger value="decide" data-testid="pane-decide">
                          Decide
                        </TabsTrigger>
                        <TabsTrigger value="evidence" data-testid="pane-evidence">
                          Evidence
                        </TabsTrigger>
                      </TabsList>
                    </Tabs>
                  )}
                  <div className={cn('grid min-h-0 min-w-0 flex-1 gap-4', twoPanes ? 'lg:grid-cols-[minmax(0,1fr)_minmax(26rem,32rem)] lg:grid-rows-[minmax(0,1fr)]' : 'mx-auto w-full max-w-3xl lg:grid-rows-[minmax(0,1fr)]')}>
                    {twoPanes && (
                      // The evidence scrolls in its own column; the decision beside it does not move.
                      <section className={cn('min-h-0 min-w-0 flex-col gap-3 overflow-y-auto', pane === 'evidence' ? 'flex' : 'hidden', 'lg:flex')} aria-label="Evidence" data-testid="evidence-pane">
                        {task.evidence.map((node, i) => (
                          <KindView key={i} node={node} />
                        ))}
                      </section>
                    )}
                    <DecisionPanel
                      key={active.id}
                      review={active}
                      view={twoPanes ? task : { ...task, decide: [...task.evidence, ...task.decide] }}
                      edits={edits}
                      onEdit={onEdit}
                      checks={checks}
                      decider={decider}
                      me={me}
                      owners={lookups?.owners ?? []}
                      reviewers={(lookups?.reviewers ?? []).filter((p) => p !== active.assignee)}
                      platformTeam={team?.scope === 'all'}
                      onReassign={(to) => void reassign(to)}
                      className={cn(twoPanes && pane !== 'decide' ? 'hidden' : 'flex', 'lg:flex')}
                    />
                  </div>
                </div>
              )
            )}
          </div>
        </div>
      )}
    </PageLayout>
  );
}
