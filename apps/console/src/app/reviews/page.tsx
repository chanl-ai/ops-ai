'use client';

import * as React from 'react';
import { AlertCircle, Check, CheckCircle2, Clock, Inbox, Timer, Undo2, UserPlus, Users, X } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { EvidenceExportButton } from '@/components/files/file-actions';
import { isOpen, type ReviewRow, reviewColumns } from '@/components/reviews/review-columns';
import { ReviewDecisionForm, ReviewDetailBody } from '@/components/reviews/review-detail';
import { BulkDecisionDialog } from '@/components/reviews/bulk-decision-dialog';
import { ModelValidationDecisionForm } from '@/components/reviews/model-validation';
import { ReviewsPageLayout } from '@/components/reviews/reviews-page-layout';
import { BulkFieldDialog, toastBulk } from '@/components/shared/bulk';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { SavedViewTabs } from '@/components/shared/saved-view-tabs';
import { StatCard, StatCardGrid } from '@/components/shared/stat-card';
import { KIND_LABEL, ReviewStatusBadge, RiskBadge } from '@/components/status-badges';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useAssignReviews, useBulkDecideReviews, useDecideReview, useLookups, useReview, useReviews } from '@/hooks/queries';
import { useSticky } from '@/hooks/use-sticky';
import { useListParams } from '@/hooks/use-list-params';
import { useRunAsPrincipals } from '@/hooks/run-as-queries';
import type { ConditionInput } from '@/lib/types/model-risk';
import { pct } from '@/lib/format';
import type { Review, ReviewDecision } from '@/lib/types/domain';
import type { ReviewFilters, ReviewView } from '@/lib/types/query';

const RISK_OPTIONS = (['critical', 'high', 'medium', 'low'] as const).map((r) => ({ label: r[0].toUpperCase() + r.slice(1), value: r }));
const KIND_OPTIONS = Object.entries(KIND_LABEL).map(([value, label]) => ({ label, value }));

export default function ReviewsPage() {
  const [view, setView] = React.useState<ReviewView>('open');
  const list = useListParams<ReviewFilters>('title');
  const query = useReviews({ ...list.params, view });
  const { data: lookups } = useLookups();
  const decide = useDecideReview();
  const assign = useAssignReviews();
  const bulkDecide = useBulkDecideReviews();
  const principals = useRunAsPrincipals();
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
  const [pendingDecision, setPendingDecision] = React.useState<ReviewDecision | null>(null);
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

  const tableRows: ReviewRow[] = React.useMemo(
    () => rows.map((r) => ({ ...r, onRowClick: (x: Review) => setActiveId(x.id), rowTestId: `review-row-${r.id}` })),
    [rows],
  );

  const onDecide = (decision: ReviewDecision, reason: string, conditions?: ConditionInput[], actingAsId?: string) => {
    if (!active) return;
    setPendingDecision(decision);
    decide.mutate(
      { id: active.id, decision, reason, conditions, actingAsId },
      {
        onSuccess: (updated) => {
          if (updated.status === 'in_review' && decision === 'approved') {
            toast(`${updated.id} needs a second approver`, { description: `Your approval is recorded. Someone else in ${updated.policy.reviewers} must also approve.` });
            return;
          }
          if (updated.kind === 'model_validation' && updated.modelValidation) {
            const mv = updated.modelValidation;
            toast.success(
              decision === 'approved' ? (mv.scope === 'tier_change' ? `${mv.entryName} is now ${mv.toTier} tier` : `Validated ${mv.entryName}${mv.conditions?.length ? ` with ${mv.conditions.length === 1 ? '1 condition' : `${mv.conditions.length} conditions`}` : ''}`) : decision === 'rejected' ? `Rejected ${updated.id}` : `Returned ${updated.id} to ${mv.requestedBy}`,
              { description: 'Recorded in the model inventory and the audit log.' },
            );
          } else if (updated.kind === 'publish_request' && updated.publish) {
            toast.success(
              decision === 'approved' ? `${updated.workflowName} v${updated.publish.toVersion} is live` : decision === 'rejected' ? `Rejected ${updated.id}` : `Returned ${updated.id} to ${updated.publish.requestedBy}`,
              { description: decision === 'approved' ? 'New runs use it. Deployments move when you update them.' : 'The requester has your reason.' },
            );
          } else {
            const verb = decision === 'approved' ? 'Approved' : decision === 'rejected' ? 'Rejected' : 'Returned to agent';
            toast.success(`${verb} · ${updated.id}`, { description: decision === 'approved' ? 'The workflow run has resumed.' : 'The agent has the reason.' });
          }
          const next = rows[activeIndex + 1];
          setActiveId(next && isOpen(next) ? next.id : null);
        },
        onError: (e) => toast.error(`Couldn’t record the decision on ${active.id}`, { description: e.message }),
        onSettled: () => setPendingDecision(null),
      },
    );
  };

  const counts = query.data?.viewCounts;
  const stats = query.data?.stats;
  const facets = query.data?.facets ?? {};
  const withCounts = (column: string, options: { label: string; value: string }[]) =>
    options.map((o) => ({ ...o, count: facets[column]?.[o.value] ?? 0 }));

  return (
    <ReviewsPageLayout>
      {query.isPending ? (
        <PageSkeleton statCards={4} tableRows={8} />
      ) : query.isError && !query.data ? (
        <QueryError what="the review queue" onRetry={() => query.refetch()} retrying={query.isFetching} testId="reviews-error" />
      ) : (
        <div className="flex flex-col gap-4">
          <StatCardGrid columns={4}>
            <StatCard label="Open reviews" value={counts?.open} icon={Inbox} footer={{ text: `${stats?.unassigned ?? 0} unassigned`, subtext: `${counts?.mine ?? 0} assigned to you` }} />
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

          {query.isError && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription className="flex items-center justify-between gap-2">
                Refreshing the queue failed. These are the last results that loaded.
                <Button size="sm" variant="outline" onClick={() => query.refetch()}>
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          )}

          <SavedViewTabs
            ariaLabel="Review views"
            presets={[
              { id: 'mine', label: `Assigned to me · ${counts?.mine ?? 0}` },
              { id: 'open', label: `All open · ${counts?.open ?? 0}`, icon: Inbox },
              { id: 'overdue', label: `Past SLA · ${counts?.overdue ?? 0}`, icon: Clock },
              { id: 'resolved', label: `Resolved · ${counts?.resolved ?? 0}` },
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
                    { label: 'Approve', icon: Check, variant: 'outline', onClick: (rows) => setBulk({ kind: 'approved', rows }) },
                    { label: 'Reject', icon: X, variant: 'outline', onClick: (rows) => setBulk({ kind: 'rejected', rows }) },
                    { label: 'Return', icon: Undo2, variant: 'outline', onClick: (rows) => setBulk({ kind: 'returned', rows }) },
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
      {shown && shown.kind !== 'reassign' && (
        <BulkDecisionDialog
          open={!!bulk && bulk.kind !== 'reassign'}
          onOpenChange={(o) => !o && setBulk(null)}
          decision={shown.kind}
          reviews={shown.rows}
          isPending={bulkDecide.isPending}
          onConfirm={async (ids, reason) => {
            const kind = shown.kind as ReviewDecision;
            const res = await bulkDecide.mutateAsync({ ids, decision: kind, reason });
            toastBulk(res, kind === 'approved' ? 'Approved' : kind === 'rejected' ? 'Rejected' : 'Returned', 'review');
            setSelectionResetKey((k) => k + 1);
          }}
        />
      )}

      <DetailSheet
        open={!!active}
        onOpenChange={(o) => !o && setActiveId(null)}
        title={active?.title}
        description={active ? `${active.id} · ${active.customer} · ${KIND_LABEL[active.kind]}` : undefined}
        footerActions={active && (active.kind === 'publish_request' || active.kind === 'model_validation') ? <EvidenceExportButton input={{ kind: 'publish_request', reviewId: active.id }} /> : undefined}
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
            <ReviewDetailBody review={active} />
            {isOpen(active) &&
              (active.kind === 'model_validation' ? (
                <ModelValidationDecisionForm review={active} currentUser={lookups?.currentUser.name} owners={lookups?.owners ?? []} principals={principals.data ?? []} principalsLoading={principals.isPending} pending={pendingDecision} onDecide={onDecide} />
              ) : (
                <ReviewDecisionForm review={active} currentUser={lookups?.currentUser.name} pending={pendingDecision} onDecide={onDecide} />
              ))}
          </div>
        )}
      </DetailSheet>
    </ReviewsPageLayout>
  );
}
