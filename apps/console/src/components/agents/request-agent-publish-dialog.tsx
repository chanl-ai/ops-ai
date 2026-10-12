'use client';

import * as React from 'react';

import { EvalSummaryLine } from '@/components/evals/eval-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { EvalVersionSummary } from '@/lib/types/evals';

/**
 * Sends a draft agent version to Reviews. Workflows pin published versions only, so until another publisher
 * approves it every workflow keeps the published version (spec 01 4.5, spec 04 5.11).
 */
export function RequestAgentPublishDialog({
  open,
  onOpenChange,
  version,
  publishedVersion,
  owner,
  evalSummary,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  version: number;
  publishedVersion: number | null;
  owner: string;
  evalSummary?: EvalVersionSummary;
  onSubmit: (note: string) => Promise<unknown>;
  isPending: boolean;
}) {
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
      title={`Request publish of v${version}`}
      description={publishedVersion === null ? 'Nothing is published yet. Once approved, workflows can pin this version.' : `Workflows keep pinning v${publishedVersion} until this is approved and they are republished.`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            loadingText="Sending…"
            data-testid="confirm-agent-publish"
            onClick={async () => {
              if (note.trim().length < 4) return setError('Describe the change in a few words; the approver reads it first.');
              try {
                await onSubmit(note.trim());
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Request publish
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
          {evalSummary ? <EvalSummaryLine summary={evalSummary} /> : <span className="text-muted-foreground">No completed run yet. The request waits for it, and approving is blocked until it finishes.</span>}
        </div>
        <div className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Who approves</span>
          <span className="text-muted-foreground">Another publisher in {owner} who neither requested nor saved v{version}. At high and critical tier a second approver from the second line also approves.</span>
        </div>
      </div>
    </DialogShell>
  );
}
