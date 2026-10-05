'use client';

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';

/**
 * Confirms an approval that moves money or changes a production system. Used by the case actions tab and the
 * chat approval widget so both state the same consequence before anything runs.
 */
export function ConfirmActionDialog({
  open,
  onOpenChange,
  title,
  consequence,
  details,
  runsNow,
  note,
  confirmLabel,
  isPending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** What happens when the action runs: amount, account, system. */
  consequence: string;
  details?: { label: string; value: string }[];
  /** False when this is the first of two approvals; the action then waits for a second approver. */
  runsNow: boolean;
  /** Replaces the default "runs now / first of two" line when the action can be reversed some other way. */
  note?: string;
  confirmLabel: string;
  isPending: boolean;
  onConfirm: () => Promise<unknown>;
}) {
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) setError(null);
  }, [open]);

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !isPending && onOpenChange(o)}
      size="sm"
      title={title}
      description={note ?? (runsNow ? 'This runs as soon as you confirm and cannot be undone from Ops AI.' : 'Your approval is the first of two. It runs when a second approver confirms.')}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            onClick={async () => {
              try {
                await onConfirm();
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            {confirmLabel}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-3 text-sm">
        <p className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <span>{consequence}</span>
        </p>
        {details && details.length > 0 && (
          <dl className="grid grid-cols-[minmax(6rem,auto)_1fr] gap-x-4 gap-y-1.5 rounded-md border bg-muted/40 p-3 text-xs">
            {details.map((d) => (
              <React.Fragment key={d.label}>
                <dt className="text-muted-foreground">{d.label}</dt>
                <dd className="min-w-0 break-words">{d.value}</dd>
              </React.Fragment>
            ))}
          </dl>
        )}
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </DialogShell>
  );
}
