'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Textarea } from '@/components/ui/textarea';
import { useSession } from '@/hooks/auth-queries';
import { useDecideModuleReview } from '@/hooks/tool-module-queries';

/** tools-service's default Security team (settings.security_team_id); its approvers and admins decide module reviews. */
const SECURITY_TEAM = 'team_security';

/**
 * Security's decision on a module's pending review, shared by the module page and the Reviews page's Tool modules tab.
 * The service decides who may (an approver or admin on the Security team, never the requester); the form disables
 * itself for the requester and, under platform sign-in, for anyone without that role, saying why.
 */
export function ModuleReviewDecision({ moduleId, review, onDecided }: { moduleId: string; review: { id: string; version: string; requestedBy: string }; onDecided?: () => void }) {
  const decide = useDecideModuleReview();
  const { session } = useSession();
  const [reason, setReason] = React.useState('');
  const [error, setError] = React.useState<string>();
  const [pending, setPending] = React.useState<'approved' | 'changes_requested' | null>(null);
  React.useEffect(() => {
    setReason('');
    setError(undefined);
  }, [review.id]);

  const mine = !!session && [session.user.name, session.user.email].includes(review.requestedBy);
  // Roles exist only under platform sign-in; the mock and dev sign-in leave the decision to the service's own rule.
  const roles = session?.user.teamRoles;
  const security = !roles || ['approver', 'admin'].includes(roles[SECURITY_TEAM] ?? '');
  const blocked = mine ? 'You requested this review. Someone in Security decides it.' : !security ? 'Only an approver or admin on the Security team decides module reviews.' : undefined;

  const submit = async (decision: 'approved' | 'changes_requested') => {
    if (decision === 'changes_requested' && !reason.trim()) return setError('Say what has to change before requesting changes.');
    setError(undefined);
    setPending(decision);
    try {
      await decide.mutateAsync({ id: moduleId, reviewId: review.id, input: decision === 'approved' ? { decision } : { decision, findings: [reason.trim()] } });
      toast.success(decision === 'approved' ? `Approved v${review.version}` : `Changes requested on v${review.version}`, { description: decision === 'approved' ? 'Security approved it; the version is published.' : 'The requester sees your reason.' });
      onDecided?.();
    } catch (e) {
      // The service's refusal (403 naming who decides, 409 already decided) is what the person needs to read.
      setError((e as Error).message);
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="flex flex-col gap-3" data-testid="module-review-decision">
      <FormField id={`review-reason-${review.id}`} label="Reason" hint="Required to request changes; not needed to approve. The requester reads it." error={error}>
        <Textarea id={`review-reason-${review.id}`} rows={2} value={reason} onChange={(e) => (setReason(e.target.value), setError(undefined))} disabled={!!blocked} aria-invalid={!!error} />
      </FormField>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {blocked && <span className="mr-auto text-xs text-muted-foreground">{blocked}</span>}
        <LoadingButton variant="outline" size="sm" isLoading={pending === 'changes_requested'} disabled={!!blocked || !!pending} onClick={() => submit('changes_requested')}>
          Request changes
        </LoadingButton>
        <LoadingButton size="sm" isLoading={pending === 'approved'} disabled={!!blocked || !!pending} onClick={() => submit('approved')}>
          {blocked ? 'Security decides' : 'Approve and publish'}
        </LoadingButton>
      </div>
    </div>
  );
}
