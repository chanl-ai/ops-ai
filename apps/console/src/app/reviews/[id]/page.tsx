'use client';

import * as React from 'react';
import { UserCheck } from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';

import { keyFieldsBlock, type ReadEdits, useReadConfirmations } from '@/components/reviews/document-read';
import { OptionDecisionForm } from '@/components/reviews/option-decision-form';
import { isOpen } from '@/components/reviews/review-columns';
import { ReviewDecisionForm } from '@/components/reviews/review-detail';
import { useReviewDecider } from '@/components/reviews/use-review-decider';
import { PageLayout } from '@/components/page-layout';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { TaskPage } from '@/components/tasks/task-page';
import { taskView } from '@/components/tasks/task-regions';
import { useReview, useReviewPlace } from '@/hooks/queries';
import { useCurrentPerson } from '@/hooks/auth-queries';
import { useTeam } from '@/hooks/use-team';


export default function TaskRoute() {
  // The segment arrives still encoded in a production build ("run%3Aack%3A1"); the client encodes it again per call.
  const id = decodeURIComponent(useParams<{ id: string }>().id);
  const router = useRouter();
  const review = useReview(id);
  // The place comes with the task when the service sends it; the separate call is the fallback.
  const placeCall = useReviewPlace(review.data && !review.data.place ? id : null);
  const place = review.data?.place ?? placeCall.data;
  const me = useCurrentPerson().ids;
  const { team } = useTeam();
  const [edits, setEdits] = React.useState<ReadEdits>({});
  React.useEffect(() => {
    setEdits({});
  }, [id]);
  const checks = useReadConfirmations(id);
  const onEdit = React.useCallback((record: number, key: string, text: string) => setEdits((e) => ({ ...e, [record]: { ...e[record], [key]: text } })), []);

  const go = (to: string | undefined) => router.push(to ? `/reviews/${encodeURIComponent(to)}` : '/reviews');
  const r = review.data ?? null;
  const { onDecide, onOption, pendingDecision, pendingOption, stepUp } = useReviewDecider({
    active: r,
    edits,
    confirmed: checks.confirmed,
    // The page stays on the task just decided, now showing who decided it; Next moves on, so a second click can never
    // land on another task's decision.
    onDone: () => undefined,
  });

  if (review.isPending) return <RecordSkeleton />;
  if (review.isError || !r)
    return (
      <PageLayout icon={UserCheck} title="Human Task" backHref="/reviews">
        <QueryError what="this task" onRetry={() => review.refetch()} retrying={review.isFetching} error={review.error} testId="task-error" back={{ label: 'Back to Human Tasks', href: '/reviews' }} />
      </PageLayout>
    );

  const view = taskView(r);
  const open = isOpen(r);
  const canDecide = open && r.canDecide !== false;
  const footer = !open ? (
    <p className="border-t px-4 py-3 text-sm text-muted-foreground lg:px-6" data-testid="task-decided">
      {r.decidedBy ? `Decided by ${r.decidedBy}` : 'Decided'}
      {r.decisionReason ? `: ${r.decisionReason}` : ''}
    </p>
  ) : !canDecide ? (
    <p className="border-t px-4 py-3 text-sm text-muted-foreground lg:px-6" data-testid="review-decided-by">
      A reviewer or admin of the team that reviews this decides it.
    </p>
  ) : r.kind === 'model_validation' ? (
    // Model validation records conditions and who it acts as; that form lives in the queue's quick view.
    <p className="border-t px-4 py-3 text-sm lg:px-6">
      <Link href={`/reviews?review=${encodeURIComponent(r.id)}`} className="underline underline-offset-2">
        Decide this validation in the queue
      </Link>
    </p>
  ) : view.actions?.length ? (
    // A typed task decides by its type's actions, in order, each posting its port.
    <OptionDecisionForm
      reviewId={r.id}
      options={view.actions.map((a) => ({ name: a.port, label: a.label, consequence: a.consequence, inputs: a.inputs, reason: a.reason, tone: a.tone, stepUp: a.port === 'approve' ? r.stepUp : undefined }))}
      blocked={Object.fromEntries(view.actions.filter((a) => a.requires === 'key_fields_confirmed' || a.port === 'approve').map((a) => [a.port, keyFieldsBlock(view.read, checks.confirmed)]))}
      pending={pendingOption}
      onDecide={onOption}
      layout="footer"
      suggested={view.actions.find((a) => a.name === view.suggested)?.port}
    />
  ) : r.options?.length ? (
    <OptionDecisionForm reviewId={r.id} options={r.options} pending={pendingOption} onDecide={onOption} layout="footer" />
  ) : (
    <ReviewDecisionForm
      review={r}
      currentUser={me}
      pending={pendingDecision}
      layout="footer"
      approveBlocked={keyFieldsBlock(r.read, checks.confirmed)}
      consequence={view.consequence || undefined}
      onDecide={(d, reason, addTestCase) => onDecide(d, reason, undefined, undefined, addTestCase)}
      platformTeam={team?.scope === 'all'}
    />
  );

  return (
    <>
      {stepUp.dialog}
      <TaskPage
        review={r}
        view={view}
        edits={edits}
        onEdit={canDecide && r.read?.editable ? onEdit : undefined}
        checks={canDecide ? checks : undefined}
        queue={{
          position: place?.position ?? undefined,
          total: place?.position != null ? place.total : undefined,
          onPrev: place?.previous ? () => go(place.previous!) : undefined,
          onNext: place?.next ? () => go(place.next!) : undefined,
          onClose: () => router.push('/reviews'),
        }}
        footer={footer}
      />
    </>
  );
}
