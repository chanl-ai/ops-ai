'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/** Confirms an irreversible action by asking for the name to be typed; the action stays off until it matches. */
export function DestructiveDialog({ open, onOpenChange, title, description, confirmName, actionLabel, onConfirm, pending }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; description: string; confirmName: string; actionLabel: string; onConfirm: () => void | Promise<void>; pending?: boolean }) {
  const [typed, setTyped] = React.useState('');
  React.useEffect(() => {
    if (!open) setTyped('');
  }, [open]);
  const ok = typed === confirmName;
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={title}
      description={description}
      onSubmit={() => ok && onConfirm()}
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" variant="destructive" isLoading={pending} disabled={!ok} data-testid="destructive-confirm">
            {actionLabel}
          </LoadingButton>
        </>
      }
    >
      <FormField id="confirm-name" label={`Type ${confirmName} to confirm`}>
        <Input id="confirm-name" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" className="bg-card font-mono text-sm" />
      </FormField>
    </DialogShell>
  );
}
