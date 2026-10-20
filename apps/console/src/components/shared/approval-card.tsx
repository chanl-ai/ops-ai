'use client';

import * as React from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';

import { Confirmation, ConfirmationAccepted, ConfirmationAction, ConfirmationActions, ConfirmationRejected, ConfirmationRequest, ConfirmationTitle } from '@/components/ai-elements/confirmation';
import { Textarea } from '@/components/ui/textarea';

export type ApprovalCardState = 'pending' | 'approved' | 'rejected';

/**
 * A drafted action waiting for a person, on AI Elements' Confirmation. Without `onApprove` and `onReject` the card
 * is read-only (another person's conversation); rejecting asks for a reason first.
 */
export function ApprovalCard({
  id,
  summary,
  state,
  children,
  onApprove,
  onReject,
  busy,
}: {
  id: string;
  summary: string;
  state: ApprovalCardState;
  /** What the action will do, e.g. its arguments. */
  children?: React.ReactNode;
  onApprove?: () => void;
  onReject?: (reason: string) => void;
  busy?: boolean;
}) {
  const [rejecting, setRejecting] = React.useState(false);
  const [reason, setReason] = React.useState('');
  const decidable = !!onApprove && !!onReject;
  const approval = state === 'pending' ? { id } : { id, approved: state === 'approved' };
  return (
    <Confirmation approval={approval} state={state === 'pending' ? 'approval-requested' : 'approval-responded'} data-testid="approval-card">
      <ConfirmationTitle>{summary}</ConfirmationTitle>
      {children}
      <ConfirmationRequest>
        {rejecting && <Textarea aria-label="Reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. The amount is above the customer's limit" />}
        {!decidable && <p className="text-xs text-muted-foreground">Waiting for a person to decide.</p>}
      </ConfirmationRequest>
      {decidable && (
        <ConfirmationActions>
          {rejecting ? (
            <>
              <ConfirmationAction variant="ghost" disabled={busy} onClick={() => setRejecting(false)}>
                Cancel
              </ConfirmationAction>
              <ConfirmationAction variant="destructive" disabled={busy || !reason.trim()} onClick={() => onReject(reason.trim())}>
                Reject
              </ConfirmationAction>
            </>
          ) : (
            <>
              <ConfirmationAction variant="outline" disabled={busy} onClick={() => setRejecting(true)}>
                Reject
              </ConfirmationAction>
              <ConfirmationAction disabled={busy} onClick={onApprove}>
                Approve
              </ConfirmationAction>
            </>
          )}
        </ConfirmationActions>
      )}
      <ConfirmationAccepted>
        <p className="flex items-center gap-1.5 text-sm text-success-text">
          <CheckCircle2 className="size-4" /> Approved
        </p>
      </ConfirmationAccepted>
      <ConfirmationRejected>
        <p className="flex items-center gap-1.5 text-sm text-destructive">
          <XCircle className="size-4" /> Rejected
        </p>
      </ConfirmationRejected>
    </Confirmation>
  );
}
