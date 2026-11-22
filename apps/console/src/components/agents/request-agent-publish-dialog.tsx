'use client';

import * as React from 'react';

import { EvalSteps, isEvalProblem } from '@/components/agents/eval-problems';
import { PublishDialog, type BlockerRow } from '@/components/shared/publish-dialog';
import { Button } from '@/components/ui/button';
import { useAgentPublishCheck, useAgentPublishPreview } from '@/hooks/queries';
import { HEADING } from '@/components/agents/brief-headings';
import type { PublishBlocker, Ref } from '@/lib/types/references';
import type { PublishPreview } from '@/lib/types/publish-preview';

/**
 * Publishes a draft agent version, or sends it to Reviews when the team's publish policy needs a second person. The
 * dialog asks the policy first (`publishPreview`) and says which will happen, so it never promises a review the
 * publish does not open (agents-1). Workflows pin published versions only (spec 01 4.5, spec 04 5.11).
 */

/** Why a publish goes live at once, finishing "Publishes immediately: …". */
function immediately(p: PublishPreview, owner: string): string {
  if (p.reviewReason === 'dev_auto_approve') return 'this environment approves publishes automatically, so no one else reviews it.';
  if (p.reviewReason === 'policy_never') return `${owner} publishes agents without review.`;
  return `only its name, role or channels changed, which ${owner} publishes without review.`;
}

/** Why a publish waits for review. */
function reviewed(p: PublishPreview, owner: string): string {
  if (p.reviewReason === 'policy_always') return `${owner} reviews every agent publish.`;
  if (p.reviewReason === 'security_change') return 'It changes guardrails, approvals, access or egress, which is always reviewed.';
  if (p.reviewReason === 'policy_unread') return 'The workspace’s review setting could not be read just now, so this publish waits for a review to be safe.';
  return 'It changes what the agent can do: its tools, instructions, knowledge or limits.';
}
/** A problem from a refused publish in the check's `Blocker` shape. */
const blockerOf = (p: PublishBlocker): BlockerRow => ({ node: null, field: p.position?.field ?? null, level: 'error', code: p.kind, message: p.message });

export function RequestAgentPublishDialog({
  open,
  onOpenChange,
  version,
  publishedVersion,
  owner,
  onSubmit,
  isPending,
  agentId,
  onGoTo,
  onAddBack,
  onOpenEvals,
  adding,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  version: number;
  publishedVersion: number | null;
  owner: string;
  onSubmit: (note: string) => Promise<unknown>;
  isPending: boolean;
  agentId: string;
  /** Closes the dialog and puts the caret on the heading a problem names. */
  onGoTo: (field: string) => void;
  onAddBack: (ref: Ref) => void;
  /** Closes the dialog and shows the agent's Evals tab. */
  onOpenEvals: () => void;
  adding?: boolean;
}) {
  const preview = useAgentPublishPreview(agentId, version, open);
  const check = useAgentPublishCheck(agentId, version, open);
  // A publish the service refuses (422 `cannot_publish`) shows its own list here, the same one the check returns.
  const [refused, setRefused] = React.useState<PublishBlocker[] | null>(null);
  React.useEffect(() => {
    if (open) setRefused(null);
  }, [open]);
  const problems = refused ?? check.data?.problems ?? [];
  const blockers: BlockerRow[] = refused ? refused.map(blockerOf) : (check.data?.blockers ?? []);
  const blocked = refused ? true : check.data ? !check.data.canRequest : false;
  const p = preview.data;
  const live = p ? !p.reviewRequired : false;

  return (
    <PublishDialog
      open={open}
      onOpenChange={onOpenChange}
      testId="publish"
      size="sm"
      title={live ? `Publish v${version}` : `Request publish of v${version}`}
      description={
        live
          ? `Publishes immediately: ${immediately(p as PublishPreview, owner)}`
          : publishedVersion === null
            ? 'Nothing is published yet. Once approved, workflows can pin this version.'
            : `Workflows keep pinning v${publishedVersion} until this is approved and they are republished.`
      }
      blockers={blockers}
      where={(b) => (b.field ? (HEADING[b.field] ?? b.field) : null)}
      onJump={(b) => b.field && (onOpenChange(false), onGoTo(b.field))}
      rowAction={(b, i) => {
        const evalProblem = problems.find((q) => q.kind === b.code && isEvalProblem(q));
        if (evalProblem)
          return (
            <div className="flex flex-col items-end gap-1">
              {evalProblem.details?.steps && <EvalSteps steps={evalProblem.details.steps} />}
              {evalProblem.kind !== 'eval_setting_unread' && (
                <Button type="button" variant="outline" size="sm" onClick={() => (onOpenChange(false), onOpenEvals())} data-testid="publish-problem-evals">
                  Open evals
                </Button>
              )}
            </div>
          );
        // A reference the team still offers but the agent lost can be put back from the row.
        const q = problems[i];
        const at = q?.kind === 'missing_reference' && q.id ? q.id.indexOf(':') : -1;
        return at > 0 && q.id ? (
          <Button type="button" variant="outline" size="sm" disabled={adding} onClick={() => onAddBack({ kind: q.id!.slice(0, at) as Ref['kind'], id: q.id!.slice(at + 1) })} data-testid="publish-problem-add-back">
            Add back
          </Button>
        ) : null;
      }}
      loadError={check.isError ? <p className="text-sm text-destructive-text">Couldn’t check the brief just now. Close this and try again.</p> : undefined}
      note={{ label: 'What changed', placeholder: 'e.g. Require a callback before any release', required: true, minLength: 4, missing: live ? 'Describe the change in a few words; it is kept with the version.' : 'Describe the change in a few words; the reviewer reads it first.' }}
      submitLabel={live ? 'Publish' : 'Request publish'}
      submittingLabel={preview.isPending ? 'Checking…' : live ? 'Publishing…' : 'Sending…'}
      submitTestId="confirm-agent-publish"
      disabled={blocked}
      pending={isPending || preview.isPending}
      onSubmit={async (note) => {
        try {
          await onSubmit(note);
        } catch (e) {
          const err = e as { code?: string; details?: { problems?: PublishBlocker[] } };
          if (err.code === 'cannot_publish' && err.details?.problems?.length) setRefused(err.details.problems);
          throw e;
        }
      }}
    >
      {p && !live && (
        <div className="flex flex-col gap-1 text-sm" data-testid="publish-review-reason">
          <span className="font-medium">Who approves</span>
          <span className="text-muted-foreground">
            {reviewed(p, owner)} Another publisher in {owner} who neither requested nor saved v{version} approves it. At high and critical tier a second reviewer from the second line also approves.
          </span>
        </div>
      )}
    </PublishDialog>
  );
}
