'use client';

import * as React from 'react';
import { AlertCircle, Check, CheckCircle2, Clock, Inbox, Timer, Undo2, UserPlus, Users, X } from 'lucide-react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { EvidenceExportButton } from '@/components/files/file-actions';
import { isOpen, type ReviewRow, reviewColumns } from '@/components/reviews/review-columns';
import { StepUpCancelled } from '@/components/auth/reauth-dialog';
import { DecidedBy, ReviewDetailBody } from '@/components/reviews/review-detail';
import { type ReadEdits, useReadConfirmations } from '@/components/reviews/document-read';
import { BulkDecisionDialog } from '@/components/reviews/bulk-decision-dialog';
import { ReviewsPageLayout } from '@/components/reviews/reviews-page-layout';
import { TaskDecision } from '@/components/reviews/task-decision';
import { useReviewDecider } from '@/components/reviews/use-review-decider';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { countLabel, SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { KIND_LABEL, ReviewStatusBadge, RiskBadge } from '@/components/status-badges';
import { KindView } from '@/components/chat/widgets/kind-view';
import { TaskDecide } from '@/components/tasks/task-page';
import { taskView } from '@/components/tasks/task-regions';
import { Button } from '@/components/ui/button';
import { useAssignReviews, useBulkDecideReviews, useLookups, useReview, useReviewByRunKey, useReviews } from '@/hooks/queries';
import { useSticky } from '@/hooks/use-sticky';
import { useListParams } from '@/hooks/use-list-params';
import { useTeam } from '@/hooks/use-team';
import { useCurrentPerson } from '@/hooks/auth-queries';
import { pct } from '@/lib/format';
import type { Review, ReviewDecision } from '@/lib/types/domain';
import type { ReviewFilters, ReviewView } from '@/lib/types/query';

const RISK_OPTIONS = (['critical', 'high', 'medium', 'low'] as const).map((r) => ({ label: r[0].toUpperCase() + r.slice(1), value: r }));
const KIND_OPTIONS = Object.entries(KIND_LABEL).map(([value, label]) => ({ label, value }));

/** Bulk decisions go to the rows the server says the person may decide; the rest are left out. */
const decidable = (rows: Review[]) => rows.filter((r) => r.canDecide !== false);

/**
 * All tasks (c-460): every Human Tasks view as a table, with its filters, stats, bulk decide and export, and a quick view
 * that decides through the same forms as the queue. The queue and task page is /reviews; a row opens its task there.
 */
export default function AllTasksPage() {
  // Tool module reviews are publish requests in this one queue (c-163), not a tab of their own.
  const [view, setView] = React.useState<ReviewView>('open');
  const list = useListParams<ReviewFilters>('title');
  const query = useReviews({ ...list.params, view });
  const { data: lookups } = useLookups();
  // Who is deciding: the signed-in person, by name and by email (platform-recorded requests carry the email), so the
  // requester of a publish is blocked from approving it.
  const me = useCurrentPerson().ids;
  const { team } = useTeam();
  const assign = useAssignReviews();
  const bulkDecide = useBulkDecideReviews();
  const [bulk, setBulk] = React.useState<{ kind: 'reassign' | ReviewDecision; rows: Review[] } | null>(null);
  const shown = useSticky(bulk);
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  // The open review lives in ?review= so links from Overview, workflows and toasts open it directly.
  const activeId = searchParams.get('review');
  const setActiveId = React.useCallback(
    (id: string | null) => router.replace(id ? `${pathname}?review=${id}` : pathname, { scroll: false }),
    [router, pathname],
  );
  // A service links to a system workflow's review by its run key before the run has a step (c-257); once found, the
  // address names the review itself.
  const byKey = useReviewByRunKey(activeId ? null : searchParams.get('runKey'));
  React.useEffect(() => {
    if (byKey.data) setActiveId(byKey.data.id);
  }, [byKey.data, setActiveId]);
  const [selectionResetKey, setSelectionResetKey] = React.useState(0);

  const rows = query.data?.data ?? [];
  const activeIndex = rows.findIndex((r) => r.id === activeId);
  // Next on the last row of a page loads the next page, then opens its first row.
  const openFirstRef = React.useRef(false);
  React.useEffect(() => {
    if (openFirstRef.current && rows.length && !query.isPlaceholderData) {
      openFirstRef.current = false;
      setActiveId(rows[0].id);
    }
  }, [rows, query.isPlaceholderData, setActiveId]);
  const offPage = useReview(activeId && activeIndex < 0 ? activeId : null);
  const active = activeIndex >= 0 ? rows[activeIndex] : (offPage.data ?? null);
  // A link to a task that was decided and closed, or never existed, says so instead of opening the plain queue.
  const missing = (offPage.error as { status?: number } | null)?.status === 404;
  React.useEffect(() => {
    if (!missing) return;
    toast.error('That task wasn’t found or is closed', { description: 'It may have been decided already, or it belongs to another team.' });
    setActiveId(null);
  }, [missing, setActiveId]);
  const options = active?.options ?? undefined;
  // The same regions and words as the task's own page (c-289); a type with none keeps today's body.
  const task = React.useMemo(() => (active ? taskView(active) : null), [active]);
  // A reviewer's corrections to the open review's document read; another review starts with none.
  const [edits, setEdits] = React.useState<ReadEdits>({});
  const checks = useReadConfirmations(active?.id);
  React.useEffect(() => {
    setEdits({});
  }, [active?.id]);
  const onEdit = React.useCallback((record: number, key: string, text: string) => setEdits((e) => ({ ...e, [record]: { ...e[record], [key]: text } })), []);

  const tableRows: ReviewRow[] = React.useMemo(
    // A row opens the task's own page; Quick view on the row peeks at it here without leaving the queue.
    () => rows.map((r) => ({ ...r, onRowClick: (x: Review) => router.push(`/reviews?review=${encodeURIComponent(x.id)}`), onPeek: (x: Review) => setActiveId(x.id), rowTestId: `review-row-${r.id}` })),
    [rows, router],
  );

  const decider = useReviewDecider({
    active,
    edits,
    confirmed: checks.confirmed,
    // The panel stays on the task just decided, now showing who decided it; moving on is the person's own Next, so
    // a second click can never land on another task's Approve.
    onDone: () => undefined,
  });

  const counts = query.data?.viewCounts;
  const stats = query.data?.stats;
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, options: { label: string; value: string }[]) =>
    options.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));

  return (
    <ReviewsPageLayout title="All tasks" description="Every Human Task in this team, with filters, bulk decisions and export" backHref="/reviews">
      {query.isPending ? (
        <PageSkeleton statCards={4} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="the review queue" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} testId="reviews-error" />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            {/* These count the agents queue (runs and publishes); module reviews are tools-service's and counted on their tab. */}
            <StatCard
              label="Open reviews"
              value={counts?.open}
              icon={Inbox}
              footer={{ text: `${stats?.unassigned ?? 0} unassigned, ${counts?.mine ?? 0} assigned to you`, subtext: 'Runs and publishes, tool modules included' }}
            />
            <StatCard
              label="Past SLA"
              value={counts?.overdue}
              icon={AlertCircle}
              footer={{ text: counts?.overdue ? 'Runs stay paused until decided' : 'Nothing overdue', subtext: 'Across all workflows' }}
            />
            <StatCard
              label="Median time to decision"
              value={stats ? `${stats.medianDecisionMinutes}m` : undefined}
              icon={Timer}
              trend={stats?.decidedToday ? { value: `${Math.abs(stats.medianDecisionTrendMinutes)}m`, direction: stats.medianDecisionTrendMinutes <= 0 ? 'down' : 'up', isPositive: stats.medianDecisionTrendMinutes <= 0 } : undefined}
              footer={
                stats?.decidedToday
                  ? { text: `${Math.abs(stats.medianDecisionTrendMinutes)} min ${stats.medianDecisionTrendMinutes <= 0 ? 'faster' : 'slower'} than last week`, subtext: 'Pause to decision, last 7 days' }
                  : { text: 'No decisions yet', subtext: 'Pause to decision, last 7 days' }
              }
            />
            <StatCard
              label="Approved as proposed"
              value={stats ? pct(stats.approvedAsProposedRate) : undefined}
              icon={CheckCircle2}
              footer={{ text: `${stats?.decidedToday ?? 0} decided today`, subtext: 'Last 7 days' }}
            />
          </StatCardGrid>

          <SavedViewTabs
            ariaLabel="Review views"
            presets={[
              { id: 'mine', label: countLabel('Assigned to me', counts?.mine) },
              { id: 'open', label: countLabel('All open', counts?.open), icon: Inbox },
              { id: 'overdue', label: countLabel('Past SLA', counts?.overdue), icon: Clock },
              { id: 'resolved', label: countLabel('Resolved', counts?.resolved) },
            ]}
            savedViews={[]}
            activePresetId={view}
            activeSavedViewId={null}
            onSelectPreset={(id) => {
              setView(id as ReviewView);
              list.reset();
              setSelectionResetKey((k) => k + 1);
            }}
            onSelectSavedView={() => undefined}
            onSaveView={() => undefined}
            onDeleteView={() => undefined}
            canSave={false}
          />

          <DataTableWithViews
            columns={reviewColumns}
            data={tableRows}
            getRowId={(r) => r.id}
            searchColumn="title"
            searchPlaceholder="Search reviews…"
            initialColumnVisibility={{ kind: false, confidence: false }}
            filters={[
              { column: 'risk', title: 'Risk', options: withCounts('risk', RISK_OPTIONS) },
              { column: 'workflowId', title: 'Workflow', options: withCounts('workflowId', (lookups?.workflows ?? []).map((w) => ({ label: w.name, value: w.id }))) },
              { column: 'kind', title: 'Type', options: withCounts('kind', KIND_OPTIONS) },
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
            bulkActions={
              view === 'resolved'
                ? []
                : [
                    {
                      label: 'Assign to me',
                      icon: UserPlus,
                      variant: 'outline',
                      onClick: (selected) =>
                        assign.mutate(
                          { ids: selected.map((r) => r.id) },
                          {
                            onSuccess: (res) => {
                              toastBulk(res, 'Assigned', 'review');
                              setSelectionResetKey((k) => k + 1);
                            },
                            onError: (e) => toast.error('Couldn’t assign those reviews', { description: e.message }),
                          },
                        ),
                    },
                    { label: 'Reassign', icon: Users, variant: 'outline', onClick: (rows) => setBulk({ kind: 'reassign', rows }) },
                    { label: 'Approve', icon: Check, variant: 'outline', onClick: (rows) => setBulk({ kind: 'approved', rows: decidable(rows) }) },
                    { label: 'Reject', icon: X, variant: 'outline', onClick: (rows) => setBulk({ kind: 'rejected', rows: decidable(rows) }) },
                    { label: 'Return', icon: Undo2, variant: 'outline', onClick: (rows) => setBulk({ kind: 'returned', rows: decidable(rows) }) },
                  ]
            }
            emptyState={
              <ListEmpty
                icon={Inbox}
                noun={view === 'resolved' ? 'resolved reviews' : 'reviews'}
                filtered={list.isFiltered}
                description={view === 'mine' ? 'Nothing is assigned to you. Pick one up from All open.' : 'When a workflow gate pauses a run, it appears here.'}
              />
            }
          />
        </div>
      )}

      <BulkFieldDialog
        open={bulk?.kind === 'reassign'}
        onOpenChange={(o) => !o && setBulk(null)}
        title={`Reassign ${shown?.rows.length ?? 0} reviews`}
        description="The new assignee gets them in Assigned to me. Their SLA clocks keep running."
        fieldLabel="Reviewer"
        options={lookups?.reviewers ?? []}
        names={(shown?.rows ?? []).map((r) => `${r.id} · ${r.title}`)}
        confirmLabel="Reassign"
        isPending={assign.isPending}
        onConfirm={async (assignee) => {
          const res = await assign.mutateAsync({ ids: bulk!.rows.map((r) => r.id), assignee });
          toastBulk(res, `Reassigned to ${assignee}:`, 'review');
          setSelectionResetKey((k) => k + 1);
        }}
      />
      {decider.stepUp.dialog}
      {shown && shown.kind !== 'reassign' && (
        <BulkDecisionDialog
          open={!!bulk && bulk.kind !== 'reassign'}
          onOpenChange={(o) => !o && setBulk(null)}
          decision={shown.kind}
          reviews={shown.rows}
          isPending={bulkDecide.isPending}
          onConfirm={async (ids, reason) => {
            const kind = shown.kind as ReviewDecision;
            // One step-up covers the whole batch when any of it needs one.
            let res;
            try {
              res = await decider.stepUp.withStepUp(`Approving ${ids.length} reviews`, (stepUpToken) => bulkDecide.mutateAsync({ ids, decision: kind, reason, stepUpToken }));
            } catch (e) {
              if (e instanceof StepUpCancelled) return;
              throw e;
            }
            toastBulk(res, kind === 'approved' ? 'Approved' : kind === 'rejected' ? 'Rejected' : 'Returned', 'review');
            setSelectionResetKey((k) => k + 1);
          }}
        />
      )}

      <DetailSheet
        open={!!active}
        onOpenChange={(o) => !o && setActiveId(null)}
        title={task?.question ?? active?.title}
        description={
          // A workflow's step is named by its workflow and step and links to its run; other reviews keep their id.
          active?.runId && active.stepName ? (
            <>
              <Link href={`/workflows/runs/${active.runId}`} className="underline underline-offset-2" data-testid="review-run-link">
                {active.workflowName}
                {active.workflowVersion != null ? ` v${active.workflowVersion}` : ''} · {active.stepName}
              </Link>
              {active.customer ? ` · ${active.customer}` : ''}
            </>
          ) : active?.origin?.kind === 'chat' ? (
            // A write held in a chat links back to the conversation it resumes.
            <Link href={`/chat/${active.origin.threadId}`} className="underline underline-offset-2" data-testid="review-open-conversation">
              Chat with {active.origin.agentName}
            </Link>
          ) : active ? (
            `${active.id} · ${active.customer} · ${KIND_LABEL[active.kind]}`
          ) : undefined
        }
        footerActions={
          active && (
            <>
              {/* The quick view; the task's own page has the room for the document beside the decision. */}
              <Button size="sm" variant="outline" asChild>
                <Link href={`/reviews?review=${encodeURIComponent(active.id)}`} data-testid="review-open-page">
                  Open
                </Link>
              </Button>
              {(active.kind === 'publish_request' || active.kind === 'model_validation') && <EvidenceExportButton input={{ kind: 'publish_request', reviewId: active.id }} />}
            </>
          )
        }
        widthClass="sm:max-w-4xl"
        tags={
          active && (
            <>
              {/* A publish request is gated on the workflow's model tier, which can differ from the review's own risk. */}
              {active.kind === 'publish_request' && active.publish?.modelEntry ? (
                <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                  Model tier <RiskBadge risk={active.publish.modelEntry.tier} />
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                  Risk <RiskBadge risk={active.risk} />
                </span>
              )}
              <ReviewStatusBadge status={active.status} />
              {active.assignee && <span className="text-xs text-muted-foreground">Assigned to {active.assignee}</span>}
              {active.decidingTeam && (
                <span className="text-xs text-muted-foreground" data-testid="review-deciding-team">
                  {active.decidingTeam.name ?? active.decidingTeam.id} decides
                </span>
              )}
            </>
          )
        }
        navigation={
          // A review opened by link that is not on the current page has no position here, so no counter is shown.
          active && activeIndex >= 0
            ? {
                currentIndex: activeIndex + (list.pagination.page - 1) * list.pagination.pageSize,
                totalCount: Math.max(query.data?.pagination.total ?? rows.length, 1),
                onPrev: activeIndex > 0 ? () => setActiveId(rows[activeIndex - 1].id) : undefined,
                onNext:
                  activeIndex < rows.length - 1
                    ? () => setActiveId(rows[activeIndex + 1].id)
                    : list.pagination.page < (query.data?.pagination.totalPages ?? 1)
                      ? () => {
                          openFirstRef.current = true;
                          list.setPagination({ ...list.pagination, page: list.pagination.page + 1 });
                        }
                      : undefined,
              }
            : undefined
        }
        testId="review-sheet"
        scrollKey={active?.id}
      >
        {active && (
          <div className="flex flex-col gap-6">
            {task && !task.legacy ? (
              <>
                <DecidedBy review={active} />
                {task.evidence.map((node, i) => (
                  <KindView key={i} node={node} />
                ))}
                <TaskDecide
                  review={active}
                  view={task}
                  edits={edits}
                  onEdit={active.read?.editable && isOpen(active) && active.canDecide !== false ? onEdit : undefined}
                  checks={isOpen(active) && active.canDecide !== false ? checks : undefined}
                />
              </>
            ) : (
              <ReviewDetailBody
                review={active}
                edits={edits}
                onEdit={active.read?.editable && isOpen(active) && active.canDecide !== false ? onEdit : undefined}
                checks={isOpen(active) && active.canDecide !== false ? checks : undefined}
              />
            )}
            <TaskDecision review={active} view={task} checks={checks} decider={decider} me={me} owners={lookups?.owners ?? []} platformTeam={team?.scope === 'all'} layout="sheet">
              {({ choice, decide }) => (
                <>
                  {choice}
                  {decide}
                </>
              )}
            </TaskDecision>
          </div>
        )}
      </DetailSheet>
    </ReviewsPageLayout>
  );
}
