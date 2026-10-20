'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

/**
 * Sends a saved draft to Reviews. Another person approves it there, and only then does it start live runs; until
 * then a test run is the only way to run it.
 */
export function PublishDefinitionDialog({
  open,
  onOpenChange,
  version,
  liveVersion,
  onRequest,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  version: number;
  liveVersion: number | null;
  onRequest: (note: string) => Promise<unknown>;
}) {
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string>();
  const [pending, setPending] = React.useState(false);
  React.useEffect(() => {
    if (open) {
      setNote('');
      setError(undefined);
    }
  }, [open]);

  const submit = async () => {
    setPending(true);
    try {
      await onRequest(note.trim());
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The request was not sent');
    } finally {
      setPending(false);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={`Publish version ${version}`}
      description={liveVersion ? `Replaces version ${liveVersion} for new runs once another person approves it in Reviews. Runs under way keep their version.` : 'Goes live once another person approves it in Reviews.'}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <LoadingButton type="button" onClick={submit} isLoading={pending} loadingText="Sending…" data-testid="definition-publish-submit">
            Request publish
          </LoadingButton>
        </>
      }
    >
      <FormField id="definition-publish-note" label="What changed" optional hint="The reviewer reads this beside the steps that changed." error={error}>
        <Textarea id="definition-publish-note" value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="e.g. Refunds over 100 now wait for a review" />
      </FormField>
    </DialogShell>
  );
}
