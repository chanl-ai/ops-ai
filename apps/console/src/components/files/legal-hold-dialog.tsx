'use client';

import * as React from 'react';

import { SelectedList } from '@/components/shared/bulk';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

/** Place or release a legal hold on one or more files. A reason is required both ways and goes into the audit log. */
export function LegalHoldDialog({
  open,
  onOpenChange,
  hold,
  names,
  isPending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  /** True places a hold, false releases it. */
  hold: boolean;
  names: string[];
  isPending: boolean;
  onConfirm: (reason: string) => Promise<unknown>;
}) {
  const [reason, setReason] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setReason('');
      setError(null);
    }
  }, [open]);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={hold ? 'Place legal hold' : 'Release legal hold'}
      description={
        hold
          ? 'Held files cannot be deleted or have their retention changed, by anyone, until the hold is released. Retention dates stop applying while the hold is on.'
          : 'Released files go back to their retention class. Any file past its delete-after date is deleted at the next retention run.'
      }
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            variant={hold ? 'default' : 'destructive'}
            onClick={async () => {
              if (!reason.trim()) return setError(hold ? 'Give the matter or reason for the hold.' : 'Say why the hold is released.');
              try {
                await onConfirm(reason.trim());
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            {hold ? 'Place hold' : 'Release hold'}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="hold-reason" label={hold ? 'Matter or reason' : 'Reason for release'} error={error ?? undefined}>
          <Textarea id="hold-reason" rows={2} value={reason} aria-invalid={!!error} onChange={(e) => (setReason(e.target.value), setError(null))} placeholder={hold ? 'e.g. LH-2026-030: card dispute litigation' : 'e.g. Matter closed by Legal'} />
        </FormField>
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">Applies to {names.length} selected</p>
          <SelectedList names={names} />
        </div>
      </div>
    </DialogShell>
  );
}
