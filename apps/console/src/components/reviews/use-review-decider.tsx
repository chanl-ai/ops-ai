'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { StepUpCancelled, useStepUpGate } from '@/components/auth/reauth-dialog';
import { decisionToast } from '@/components/reviews/decision-toast';
import { correctedRecords, hasCorrections, type ReadConfirmed, type ReadEdits } from '@/components/reviews/document-read';
import { useDecideReview } from '@/hooks/queries';
import type { ConditionInput } from '@/lib/types/model-risk';
import type { Review, ReviewDecision, ReviewOption } from '@/lib/types/domain';

/**
 * Deciding the open review, shared by the queue's quick view and the task's own page: the step-up a two-approver call
 * needs, a corrected read sent as the whole records list, an option's own call, and the toast each kind of review
 * says. `onDone` runs once the decision is recorded and the review is closed (not when it waits on a second approver).
 */
export function useReviewDecider({ active, edits, confirmed, onDone }: { active: Review | null; edits: ReadEdits; confirmed?: ReadConfirmed; onDone: () => void }) {
  const decide = useDecideReview();
  const [pendingDecision, setPendingDecision] = React.useState<ReviewDecision | null>(null);
  const [pendingOption, setPendingOption] = React.useState<string | null>(null);

  // Approving a call that needs two approvers needs a step-up the API checks; the gate asks once per 5 minutes and retries with the token.
  const stepUp = useStepUpGate();
  const onDecide = (decision: ReviewDecision, reason: string, conditions?: ConditionInput[], actingAsId?: string, addTestCase?: boolean) => {
    if (!active) return;
    setPendingDecision(decision);
    const target = active;
    // Approve sends a corrected read as the whole records list; the case opens on what was approved.
    const read = target.read;
    const inputs = decision === 'approved' && read?.editable && hasCorrections(read, edits) ? { edited: correctedRecords(read, edits) } : undefined;
    const decided = (updated: Review) => {
    if (updated.status === 'in_review' && decision === 'approved') {
      toast(`${updated.id} needs a second reviewer`, { description: `Your approval is recorded. Someone else in ${updated.policy.reviewers} must also approve.` });
      return;
    }
    if (updated.kind === 'model_validation' && updated.modelValidation) {
      const mv = updated.modelValidation;
      toast.success(
        decision === 'approved' ? (mv.scope === 'tier_change' ? `${mv.entryName} is now ${mv.toTier} tier` : `Validated ${mv.entryName}${mv.conditions?.length ? ` with ${mv.conditions.length === 1 ? '1 condition' : `${mv.conditions.length} conditions`}` : ''}`) : decision === 'rejected' ? `Rejected ${updated.id}` : `Returned ${updated.id} to ${mv.requestedBy}`,
        { description: 'Recorded in the model inventory and the audit log.' },
      );
    } else if (updated.kind === 'skill_publish' && updated.skillPublish) {
      const sp = updated.skillPublish;
      toast.success(
        decision === 'approved' ? `Published ${sp.skillName} v${sp.toVersion}` : decision === 'rejected' ? `Rejected ${updated.id}` : `Returned ${updated.id} to ${sp.requestedBy}`,
        { description: decision === 'approved' ? 'Agents keep their pinned version until their owners move it.' : 'The requester has your reason.' },
      );
    } else if (updated.kind === 'template_submission' && updated.templateSubmission) {
      const ts = updated.templateSubmission;
      toast.success(
        decision === 'approved' ? `Published template ${ts.templateName}` : decision === 'rejected' ? `Rejected ${updated.id}` : `Returned ${updated.id} to ${ts.submittedBy}`,
        { description: decision === 'approved' ? 'Every team can now pick it under Agents → Templates.' : 'The submitter has your reason.' },
      );
    } else if (updated.kind === 'agent_publish' && updated.agentPublish) {
      const ap = updated.agentPublish;
      toast.success(
        decision === 'approved' ? `Published ${ap.agentName} v${ap.version}` : decision === 'rejected' ? `Rejected ${updated.id}` : `Returned ${updated.id} to ${ap.requestedBy}`,
        { description: decision === 'approved' ? 'Workflows can pin it now; each adopts it on its next publish.' : 'The requester has your reason.' },
      );
    } else if (updated.kind === 'publish_request' && updated.publish) {
      toast.success(
        decision === 'approved' ? `${updated.workflowName} v${updated.publish.toVersion} is live` : decision === 'rejected' ? `Rejected ${updated.id}` : `Returned ${updated.id} to ${updated.publish.requestedBy}`,
        { description: decision === 'approved' ? 'New runs use it. Deployments move when you update them.' : 'The requester has your reason.' },
      );
    } else {
      const t = decisionToast(updated, decision);
      toast.success(t.title, { description: t.description });
    }
    if (addTestCase && decision !== 'approved' && updated.testTarget) {
      toast(`Added a draft case to ${updated.testTarget.name}’s suite`, { description: 'It shows under Evals → Suites. The owner activates it before the gate runs it.' });
    }
    onDone();
    };
    stepUp
      .withStepUp(`Approving ${target.id}`, (stepUpToken) => decide.mutateAsync({ id: target.id, decision, reason, conditions, actingAsId, addTestCase, inputs, stepUpToken }), { upfront: decision === 'approved' && !!target.stepUp })
      .then(decided, (e) => {
        if (!(e instanceof StepUpCancelled)) toast.error(`Couldn’t record the decision on ${target.id}`, { description: (e as Error).message });
      })
      .finally(() => setPendingDecision(null));
  };

  /** One of the step's options: the API mints the token for that option's call; an option whose policy asks for a step-up is confirmed first. */
  const onOption = (option: ReviewOption, input: { inputs: Record<string, unknown>; reason: string }) => {
    if (!active) return;
    const target = active;
    setPendingOption(option.name);
    // A typed task's approve sends a corrected read the way the decision form does, as the whole records list, and the
    // key fields the person confirmed, which the server counts before it lets an approve through.
    const read = target.read;
    const approving = option.name === 'approve';
    const inputs = {
      ...input.inputs,
      ...(approving && read?.editable && hasCorrections(read, edits) ? { edited: correctedRecords(read, edits) } : {}),
      ...(approving && confirmed && Object.keys(confirmed).length ? { confirmed } : {}),
    };
    stepUp
      .withStepUp(`Deciding ${target.id}`, (stepUpToken) => decide.mutateAsync({ id: target.id, decision: option.name, inputs, reason: input.reason || undefined, stepUpToken }), { upfront: !!option.stepUp })
      .then(
        (updated) => {
          if (updated.status === 'in_review') {
            toast(`${updated.id} needs a second reviewer`, { description: `Your decision is recorded. Someone else in ${updated.policy.reviewers} must also approve.` });
            return;
          }
          toast.success(`${option.name.charAt(0).toUpperCase()}${option.name.slice(1)} · ${updated.id}`, { description: 'The run has resumed with your decision; its outcome is on the case.' });
          onDone();
        },
        (e) => {
          if (!(e instanceof StepUpCancelled)) toast.error(`Couldn’t record the decision on ${target.id}`, { description: (e as Error).message });
        },
      )
      .finally(() => setPendingOption(null));
  };

  // The gate's dialog renders once on the page that holds it; bulk decisions there reuse the same gate.
  return { onDecide, onOption, pendingDecision, pendingOption, stepUp };
}
