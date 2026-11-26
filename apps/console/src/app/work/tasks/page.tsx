'use client';

import * as React from 'react';
import Link from 'next/link';
import { Search, Table2, UserCheck, X } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { KindView } from '@/components/chat/widgets/kind-view';
import { PageLayout } from '@/components/page-layout';
import { DecisionPanel } from '@/components/reviews/decision-panel';
import { type ReadEdits, useReadConfirmations } from '@/components/reviews/document-read';
import { PickATask, TaskQueue } from '@/components/reviews/task-queue';
import { useReviewDecider } from '@/components/reviews/use-review-decider';
import { QueryError } from '@/components/shared/query-states';
import { taskView } from '@/components/tasks/task-regions';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAssignReviews, useLookups, useReview, useReviewByRunKey, useReviewPlace, useReviews } from '@/hooks/queries';
import { useCurrentPerson } from '@/hooks/auth-queries';
import { useTeam } from '@/hooks/use-team';
import { useDebounced } from '@/hooks/use-debounced';
import { cn } from '@/lib/utils';
import type { Review } from '@/lib/types/domain';
import type { ReviewView } from '@/lib/types/query';

const VIEWS = ['open', 'mine', 'overdue'] as const satisfies readonly ReviewView[];
const PAGE = 50;

/**
 * Human Tasks as queue and task (layout A): the queue grouped by case on the left, the open
 * task's evidence beside a decision panel that keeps Decide in view. From 1280 px the queue and the task sit side by
 * side, below that they take turns; from 1024 px the evidence and the decision sit side by side, below that they take
 * turns behind an Evidence and Decide switch. The app's navigation stays as on every other page. The open task is
 * ?review= (and ?runKey= resolves to one), as every link into a task already reads it. Every
 * view as a table, with bulk decisions and export, is All tasks.
 */
/** Whether the window is at least `px` wide; false until it has been measured, as on the server. */
function useMinWidth(px: number) {
  const [wide, setWide] = React.useState(false);
  React.useEffect(() => {
    const mql = window.matchMedia(`(min-width: ${px}px)`);
    const on = () => setWide(mql.matches);
    on();
    mql.addEventListener('change', on);
    return () => mql.removeEventListener('change', on);
  }, [px]);
  return wide;
}

export default function HumanTasksPage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const view: ReviewView = (VIEWS as readonly string[]).includes(params.get('view') ?? '') ? (params.get('view') as ReviewView) : 'open';
  const activeId = params.get('review');
  const [pageSize, setPageSize] = React.useState(PAGE);
  // The server matches the title, the customer and the case's name; nothing is filtered in the browser.
  const [typed, setTyped] = React.useState('');
  const search = useDebounced(typed.trim());
  const query = useReviews({ view, group: 'case', page: 1, pageSize, ...(search ? { search } : {}) });
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
  // A service links to a system workflow's review by its run key before the run has a step.
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
    action: (r) => (r.caseId ? { label: 'Open case', onClick: () => router.push(`/work/cases/${r.caseId}`) } : undefined),
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

  const assignToMe = async () => {
    if (!active) return;
    try {
      await assign.mutateAsync({ ids: [active.id] });
    } catch (e) {
      toast.error('Couldn’t assign the task', { description: (e as Error).message });
      return;
    }
    toast.success('Assigned to you', { description: `${active.title} is in your Assigned to me.` });
  };

  const twoPanes = !!task?.evidence.some((n) => n.type === 'viewer');
  const wide = useMinWidth(1024);

  // The open task as the reading pane: beside the list from 1024 px, over it as a sheet below that.
  const taskPane = !active ? (
    query.isPending || fetched.isLoading || byKey.isLoading ? (
      <Skeleton className="h-96 w-full rounded-lg" />
    ) : missing ? (
      <QueryError what="this task" onRetry={() => fetched.refetch()} error={fetched.error} retrying={fetched.isFetching} testId="task-error" />
    ) : rows.length ? (
      // The queue says when nothing is left; the pane only says what to do next.
      <PickATask />
    ) : null
  ) : (
    task && (
      // `review-sheet` names the open task wherever it opens, as on /govern/reviews; both decide through TaskDecision.
      <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3" data-testid="review-sheet">
        {twoPanes && (
          <Tabs value={pane} onValueChange={(v) => setPane(v as 'decide' | 'evidence')} className="2xl:hidden">
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
        <div className={cn('grid min-h-0 min-w-0 flex-1 gap-4', twoPanes ? '2xl:grid-cols-[minmax(0,1fr)_minmax(26rem,32rem)] 2xl:grid-rows-[minmax(0,1fr)]' : 'w-full lg:grid-rows-[minmax(0,1fr)]')}>
          {twoPanes && (
            // The evidence scrolls in its own column; the decision beside it does not move.
            <section className={cn('min-h-0 min-w-0 flex-col gap-3 overflow-y-auto', pane === 'evidence' ? 'flex' : 'hidden', '2xl:flex')} aria-label="Evidence" data-testid="evidence-pane">
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
            onAssignToMe={() => void assignToMe()}
            place={place.data ? { ...place.data, onGo: (id) => go({ review: id }) } : undefined}
            className={cn(twoPanes && pane !== 'decide' ? 'hidden' : 'flex', '2xl:flex')}
          />
        </div>
      </div>
    )
  );

  return (
    // The page title block is dropped (the top bar names the page); it stays for screen readers.
    <PageLayout icon={UserCheck} title="Human Tasks" className="min-h-0 flex-1 pb-0" headerClassName="sr-only" contentClassName="flex min-h-0 flex-1 flex-col">
      {decider.stepUp.dialog}
      {query.isError && !query.data ? (
        <QueryError what="Human Tasks" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} testId="reviews-error" />
      ) : (
        <div className="flex min-h-0 flex-1 overflow-clip rounded-lg border bg-card" data-testid="queue-and-task">
          {/* The list column: a fixed width from 1024 px so the tabs never wrap; the whole width below it. */}
          <aside className="flex min-h-0 w-full flex-col border-r lg:w-[23rem] lg:shrink-0 xl:w-[24rem]" aria-label="Tasks">
            <div className="flex flex-col gap-3 border-b p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs text-muted-foreground">Soonest due first. Tasks on one case sit together under its name.</p>
                <Button variant="ghost" size="icon" asChild>
                  <Link href="/govern/reviews" aria-label="All tasks as a table" title="All tasks as a table" data-testid="all-tasks">
                    <Table2 />
                  </Link>
                </Button>
              </div>
              <Tabs
                value={view}
                onValueChange={(id) => {
                  setPageSize(PAGE);
                  go({ view: id as ReviewView, review: null });
                }}
              >
                <TabsList className="grid w-full grid-cols-3" aria-label="Human Tasks views">
                  <TabsTrigger value="open" className="gap-1 px-1 text-xs sm:text-sm" data-testid="view-open">
                    All open
                    {counts?.open != null && <span className="font-normal text-muted-foreground tabular-nums">{counts.open}</span>}
                  </TabsTrigger>
                  <TabsTrigger value="mine" className="gap-1 px-1 text-xs sm:text-sm" data-testid="view-mine">
                    Assigned to me
                    {counts?.mine != null && <span className="font-normal text-muted-foreground tabular-nums">{counts.mine}</span>}
                  </TabsTrigger>
                  <TabsTrigger value="overdue" className="gap-1 px-1 text-xs sm:text-sm" data-testid="view-overdue">
                    Past SLA
                    {counts?.overdue != null && <span className="font-normal text-muted-foreground tabular-nums">{counts.overdue}</span>}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              <InputGroup>
                <InputGroupAddon>
                  <Search />
                </InputGroupAddon>
                <InputGroupInput
                  type="search"
                  value={typed}
                  onChange={(e) => {
                    setTyped(e.target.value);
                    setPageSize(PAGE);
                  }}
                  placeholder="Search tasks, customers, cases"
                  aria-label="Search Human Tasks"
                  data-testid="tasks-search"
                />
              </InputGroup>
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-2">
              <TaskQueue
                rows={rows}
                total={query.data?.pagination.total ?? rows.length}
                activeId={active?.id ?? null}
                loading={query.isPending}
                onOpen={open}
                onMore={() => setPageSize((n) => n + PAGE)}
                loadingMore={query.isFetching}
                search={search}
              />
            </div>
          </aside>
          {/* One reading pane at every width, so a half-made decision survives crossing 1024 px: beside the list from
              1024, and below it over the list as a sheet from the bottom, closed back to the same place in the list. */}
          {!wide && showTask && !!active && <div className="fixed inset-0 z-40 bg-black/50" aria-hidden onClick={() => setShowTask(false)} />}
          <section
            className={cn(
              'min-h-0 min-w-0 flex-col bg-background',
              wide ? 'flex flex-1 overflow-y-auto p-4' : showTask && active ? 'fixed inset-x-0 bottom-0 z-50 flex h-[90dvh] overflow-y-auto rounded-t-xl border-t p-3 pt-12 shadow-lg' : 'hidden',
            )}
            role={wide ? undefined : 'dialog'}
            aria-modal={wide ? undefined : true}
            aria-label={active?.title ?? 'Task'}
            onKeyDown={(e) => {
              if (!wide && e.key === 'Escape') setShowTask(false);
            }}
            data-testid={wide ? 'task-pane' : 'task-sheet'}
          >
            {!wide && (
              <Button type="button" variant="ghost" size="icon" className="absolute top-2 right-2" aria-label="Close task" onClick={() => setShowTask(false)} data-testid="back-to-queue">
                <X />
              </Button>
            )}
            {taskPane}
          </section>
        </div>
      )}
    </PageLayout>
  );
}
