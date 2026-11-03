'use client';

import { ConnectWait } from '@/components/reviews/connect-wait';
import { QueryError } from '@/components/shared/query-states';
import { Section } from '@/components/shared/surface';
import { Skeleton } from '@/components/ui/skeleton';
import { useReview } from '@/hooks/queries';
import type { EngineRun } from '@/lib/types/engine';

/** The event a step parks on while it waits for a person to connect their own account of an app. */
const CONNECTED = 'app_account.connected';

/** The Human Task a run waits on when a step needs a person's own account; null for any other wait. */
export function connectTaskId(run: Pick<EngineRun, 'id' | 'waiting'>): string | null {
  const payload = run.waiting?.payload;
  if (!payload || payload.kind !== 'external' || payload.event !== CONNECTED) return null;
  // The task's id is the step's when the park names it, else the run's, as Human Tasks lists it.
  return typeof payload.step_id === 'string' && payload.step_id ? payload.step_id : run.id;
}

/**
 * A run waiting for a person's own account shows its Human Task here, with the same actions as in Human Tasks: the
 * person connects their account, or someone allowed runs the step as the team account.
 */
export function RunConnectTask({ taskId }: { taskId: string }) {
  const review = useReview(taskId);
  if (review.isPending) return <Skeleton className="h-28 w-full" />;
  if (review.isError) return <QueryError what="the task this run waits on" error={review.error} onRetry={() => review.refetch()} retrying={review.isFetching} />;
  const r = review.data;
  return (
    <Section title={r.connect?.person ? `Human Task for ${r.connect.person}` : 'Human Task'} description={r.title} flush>
      <div data-testid="run-connect-task">
        <ConnectWait review={r} />
      </div>
    </Section>
  );
}
