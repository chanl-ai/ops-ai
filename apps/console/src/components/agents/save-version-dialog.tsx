'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/**
 * Confirms a save as a new agent version. Workflows keep the version they were published with,
 * so the dialog says which workflows will not see the change until they are republished.
 */
export function SaveVersionDialog({
  open,
  onOpenChange,
  nextVersion,
  sections,
  pinnedWorkflows,
  onSave,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  nextVersion: number;
  sections: string[];
  pinnedWorkflows: string[];
  onSave: (note: string) => Promise<unknown>;
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
      title={`Save as v${nextVersion}`}
      description={`Changes: ${sections.join(', ')}.`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            loadingText="Saving…"
            onClick={async () => {
              try {
                await onSave(note.trim());
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Save v{nextVersion}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="save-note" label="What changed" optional error={error ?? undefined} hint="Shown in the agent's history.">
          <Input id="save-note" autoFocus value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Require a callback before any release" />
        </FormField>
        {pinnedWorkflows.length > 0 && (
          <p className="rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
            {pinnedWorkflows.join(', ')} keep{pinnedWorkflows.length === 1 ? 's' : ''} running the current version until republished.
          </p>
        )}
      </div>
    </DialogShell>
  );
}
