'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PublishProblems } from '@/components/agents/publish-problems';
import { useAgentPublishCheck, useAgentPublishPreview } from '@/hooks/queries';
import type { Ref } from '@/lib/types/references';
import type { PublishBlocker } from '@/lib/types/references';
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
  const problems = refused ?? check.data?.problems ?? [];
  const blocked = refused ? true : check.data ? !check.data.canRequest : false;
  const p = preview.data;
  const live = p ? !p.reviewRequired : false;
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setNote('');
      setError(null);
      setRefused(null);
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
            disabled={blocked}
            isLoading={isPending || preview.isPending}
            loadingText={preview.isPending ? 'Checking…' : live ? 'Publishing…' : 'Sending…'}
            data-testid="confirm-agent-publish"
            onClick={async () => {
              if (note.trim().length < 4) return setError(live ? 'Describe the change in a few words; it is kept with the version.' : 'Describe the change in a few words; the reviewer reads it first.');
              try {
                await onSubmit(note.trim());
                onOpenChange(false);
              } catch (e) {
                const err = e as { code?: string; details?: { problems?: PublishBlocker[] } };
                if (err.code === 'cannot_publish' && err.details?.problems?.length) setRefused(err.details.problems);
                else setError((e as Error).message);
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
        {check.isError && <p className="text-sm text-destructive-text">Couldn’t check the brief just now. Close this and try again.</p>}
        <PublishProblems problems={problems} onGoTo={(f) => (onOpenChange(false), onGoTo(f))} onAddBack={onAddBack} adding={adding} onOpenEvals={() => (onOpenChange(false), onOpenEvals())} />
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
