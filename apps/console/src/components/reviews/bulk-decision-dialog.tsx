'use client';

import * as React from 'react';
import { CheckCircle2, MinusCircle } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { RiskBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import type { Review, ReviewDecision } from '@/lib/types/domain';

const VERB: Record<ReviewDecision, string> = { approved: 'Approve', rejected: 'Reject', returned: 'Return' };

/**
 * Preview of which selected reviews the server will accept. It mirrors the server's rule (bulk approval
 * only for medium/low risk with a single approver) so the reviewer sees exclusions before confirming;
 * the server still decides and its skipped list is what gets reported.
 */
export function bulkEligibility(r: Review, decision: ReviewDecision): string | null {
  if (decision !== 'approved') return null;
  if (r.risk === 'critical' || r.risk === 'high') return `${r.risk[0].toUpperCase()}${r.risk.slice(1)} risk needs an individual decision`;
  if (r.policy.fourEyes) return 'Needs two approvers';
  return null;
}

export function BulkDecisionDialog({
  open,
  onOpenChange,
  decision,
  reviews,
  onConfirm,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  decision: ReviewDecision;
  reviews: Review[];
  onConfirm: (ids: string[], reason: string) => Promise<unknown>;
  isPending: boolean;
}) {
  const [reason, setReason] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setReason('');
      setError(null);
    }
  }, [open]);

  const rows = reviews.map((r) => ({ r, excluded: bulkEligibility(r, decision) }));
  const eligible = rows.filter((x) => !x.excluded).map((x) => x.r.id);
  const needsReason = decision !== 'approved';

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={`${VERB[decision]} ${eligible.length} of ${reviews.length} reviews`}
      description={
        decision === 'approved'
          ? 'Each approved run resumes and takes the proposed action.'
          : decision === 'rejected'
            ? 'Each rejected run stops. The agent receives your reason.'
            : 'Each run goes back to its agent with your reason.'
      }
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            disabled={!eligible.length}
            variant={decision === 'rejected' ? 'destructive' : 'default'}
            onClick={async () => {
              if (needsReason && !reason.trim()) return setError('Add a reason; it is recorded on every review.');
              try {
                await onConfirm(eligible, reason.trim());
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            {VERB[decision]} {eligible.length}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <ul className="divide-y rounded-lg border" data-testid="bulk-decision-list">
          {rows.map(({ r, excluded }) => (
            <li key={r.id} className="flex items-center gap-3 px-3 py-2">
              {excluded ? <MinusCircle className="size-4 shrink-0 text-muted-foreground" /> : <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm">{r.title}</div>
                <div className="text-xs text-muted-foreground">
                  <span className="font-mono">{r.id}</span> · {excluded ?? r.customer}
                </div>
              </div>
              <RiskBadge risk={r.risk} />
            </li>
          ))}
        </ul>
        {needsReason || error ? (
          <FormField id="bulk-reason" label="Reason" optional={!needsReason} error={error ?? undefined} hint="Recorded in the audit log on each review.">
            <Textarea id="bulk-reason" value={reason} onChange={(e) => (setReason(e.target.value), setError(null))} className="min-h-20" aria-invalid={!!error} />
          </FormField>
        ) : null}
      </div>
    </DialogShell>
  );
}
