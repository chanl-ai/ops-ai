'use client';

import * as React from 'react';

import { EvalSummaryLine } from '@/components/evals/eval-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAgentPublishPreview } from '@/hooks/queries';
import type { EvalVersionSummary } from '@/lib/types/evals';
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
export function RequestAgentPublishDialog({
  open,
  onOpenChange,
  version,
  publishedVersion,
  owner,
  evalSummary,
  onSubmit,
  isPending,
  agentId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  version: number;
  publishedVersion: number | null;
  owner: string;
  evalSummary?: EvalVersionSummary;
  onSubmit: (note: string) => Promise<unknown>;
  isPending: boolean;
  agentId: string;
}) {
  const preview = useAgentPublishPreview(agentId, version, open);
  const p = preview.data;
  const live = p ? !p.reviewRequired : false;
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setNote('');
      setError(null);
    }
  }, [open]);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={live ? `Publish v${version}` : `Request publish of v${version}`}
      description={
        live
          ? `Publishes immediately: ${immediately(p as PublishPreview, owner)}`
          : publishedVersion === null
            ? 'Nothing is published yet. Once approved, workflows can pin this version.'
            : `Workflows keep pinning v${publishedVersion} until this is approved and they are republished.`
      }
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending || preview.isPending}
            loadingText={preview.isPending ? 'Checking…' : live ? 'Publishing…' : 'Sending…'}
            data-testid="confirm-agent-publish"
            onClick={async () => {
              if (note.trim().length < 4) return setError(live ? 'Describe the change in a few words; it is kept with the version.' : 'Describe the change in a few words; the reviewer reads it first.');
              try {
                await onSubmit(note.trim());
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            {live ? 'Publish' : 'Request publish'}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="agent-publish-note" label="What changed" error={error ?? undefined}>
          <Input id="agent-publish-note" autoFocus value={note} onChange={(e) => (setNote(e.target.value), setError(null))} placeholder="e.g. Require a callback before any release" aria-invalid={!!error} />
        </FormField>
        <div className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Evals on v{version}</span>
          {evalSummary ? (
            <EvalSummaryLine summary={evalSummary} />
          ) : (
            <span className="text-muted-foreground">{live ? 'No completed run yet; publishing does not wait for one.' : 'No completed run yet. The request waits for it, and approving is blocked until it finishes.'}</span>
          )}
        </div>
        {p && !live && (
          <div className="flex flex-col gap-1 text-sm" data-testid="publish-review-reason">
            <span className="font-medium">Who approves</span>
            <span className="text-muted-foreground">
              {reviewed(p, owner)} Another publisher in {owner} who neither requested nor saved v{version} approves it. At high and critical tier a second reviewer from the second line also approves.
            </span>
          </div>
        )}
      </div>
    </DialogShell>
  );
}
