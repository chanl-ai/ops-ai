'use client';

import * as React from 'react';
import Link from 'next/link';
import { Inbox, Undo2 } from 'lucide-react';

import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useWithdrawReview } from '@/hooks/queries';
import { ApiError } from '@/lib/api/contract';

/** A refused withdraw in words a person can act on. */
export function withdrawProblem(e: unknown): string {
  if (e instanceof ApiError && e.status === 403) return 'Only the person who sent this request can take it back.';
  if (e instanceof ApiError && e.status === 409) return e.code === 'not_withdrawable' ? 'This kind of request is decided in Reviews and cannot be taken back.' : 'A reviewer decided it first, so it can no longer be taken back. Reload to see the decision.';
  return e instanceof Error ? e.message : 'The request was not taken back.';
}

/**
 * The one notice for a version waiting in Reviews, on the agent, skill and workflow pages. The person who sent it may
 * Withdraw it, Edit (which withdraws it first, after asking) or, once withdrawn, Send again. Everyone else sees where
 * it waits. `reviewId` is null once the version is a draft again; the notice then offers Send again for the request
 * this person just took back.
 */
export function ReviewNotice({
  reviewId,
  version,
  detail,
  canWithdraw,
  onEdit,
  onSendAgain,
  sendingAgain,
  testId = 'review-notice',
}: {
  reviewId: string | null;
  version: number;
  /** After the title, e.g. "1 of 2 approvals". */
  detail?: string;
  /** The person sent this request and may take it back. */
  canWithdraw: boolean;
  /** The request is withdrawn: open the draft for changes. */
  onEdit?: () => void;
  /** Sends the version again; `follows` names the request just taken back (agents record it, others ignore it). */
  onSendAgain?: (follows: string) => Promise<unknown>;
  sendingAgain?: boolean;
  testId?: string;
}) {
  const withdraw = useWithdrawReview();
  const [taken, setTaken] = React.useState<string | null>(null);
  const [confirm, setConfirm] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const takeBack = async (then?: () => void) => {
    if (!reviewId) return;
    setError(null);
    try {
      await withdraw.mutateAsync(reviewId);
      setTaken(reviewId);
      then?.();
    } catch (e) {
      const said = withdrawProblem(e);
      setError(said);
      throw new Error(said);
    }
  };

  if (!reviewId) {
    if (!taken) return null;
    return (
      <Alert data-testid={`${testId}-withdrawn`}>
        <Undo2 />
        <AlertTitle>You took v{version} back from Reviews</AlertTitle>
        <AlertDescription>
          <p>It is a draft again. Change it, then send it again; the reviewer sees the earlier request’s comments.</p>
          <div className="flex gap-2">
            {onSendAgain && (
              <LoadingButton type="button" size="sm" variant="outline" isLoading={!!sendingAgain} onClick={() => void onSendAgain(taken).then(() => setTaken(null)).catch((e) => setError(e instanceof Error ? e.message : 'Not sent'))} data-testid={`${testId}-send-again`}>
                Send again
              </LoadingButton>
            )}
            <Button type="button" size="sm" variant="ghost" onClick={() => setTaken(null)}>
              Dismiss
            </Button>
          </div>
          {error && <p className="text-sm text-destructive-text">{error}</p>}
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <>
      <Alert data-testid={testId}>
        <Inbox />
        <AlertTitle>
          v{version} is waiting in Reviews{detail ? ` · ${detail}` : ''}
        </AlertTitle>
        <AlertDescription>
          <p>
            Its fields are read-only until it is decided.{' '}
            <Link href={`/work/tasks?review=${encodeURIComponent(reviewId)}`} className="underline underline-offset-2">
              Open {reviewId}
            </Link>
          </p>
          {canWithdraw && (
            <div className="flex gap-2">
              <LoadingButton type="button" size="sm" variant="outline" isLoading={withdraw.isPending} onClick={() => void takeBack().catch(() => undefined)} data-testid={`${testId}-withdraw`}>
                Withdraw
              </LoadingButton>
              <Button type="button" size="sm" variant="outline" disabled={withdraw.isPending} onClick={() => setConfirm(true)} data-testid={`${testId}-edit`}>
                Edit
              </Button>
            </div>
          )}
          {error && (
            <p className="text-sm text-destructive-text" data-testid={`${testId}-error`}>
              {error}
            </p>
          )}
        </AlertDescription>
      </Alert>
      <ConfirmActionDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Edit v${version}?`}
        consequence={`Editing takes v${version} out of review. Its request is withdrawn, and you send it again when you are done.`}
        runsNow
        note="Nothing is lost: the version becomes a draft."
        confirmLabel="Withdraw and edit"
        isPending={withdraw.isPending}
        onConfirm={() => takeBack(onEdit)}
      />
    </>
  );
}
