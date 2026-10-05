'use client';

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { BulkResult } from '@/lib/types/domain';

/**
 * Reports a bulk result honestly: one success toast for what changed, and a warning that names every
 * skipped item and why, so a partial success never reads as a full one.
 */
export function toastBulk(result: BulkResult, verb: string, noun: string, label: (id: string) => string = (id) => id) {
  const n = result.updated.length;
  if (n) toast.success(`${verb} ${n} ${noun}${n === 1 ? '' : 's'}`);
  if (result.skipped.length) {
    const byReason = new Map<string, string[]>();
    for (const s of result.skipped) byReason.set(s.reason, [...(byReason.get(s.reason) ?? []), label(s.id)]);
    toast.warning(`${result.skipped.length} skipped`, {
      description: [...byReason]
        .map(([reason, names]) => `${reason}: ${names.slice(0, 3).join(', ')}${names.length > 3 ? ` and ${names.length - 3} more` : ''}`)
        .join('\n'),
      duration: 8000,
    });
  }
  if (!n && !result.skipped.length) toast(`Nothing to ${verb.toLowerCase()}`);
}

/** Names of the selected rows, capped so a large selection does not push the form off screen. */
export function SelectedList({ names, max = 5 }: { names: string[]; max?: number }) {
  return (
    <ul className="flex flex-col gap-1 rounded-md border bg-muted/30 px-3 py-2 text-sm">
      {names.slice(0, max).map((n) => (
        <li key={n} className="truncate">
          {n}
        </li>
      ))}
      {names.length > max && <li className="text-muted-foreground">and {names.length - max} more</li>}
    </ul>
  );
}

/** One-field bulk edit (change owner, move collection, set SLA): pick a value, apply to every selected row. */
export function BulkFieldDialog({
  open,
  onOpenChange,
  title,
  description,
  fieldLabel,
  options,
  names,
  confirmLabel,
  onConfirm,
  isPending,
  prompt,
  notice,
  destructive,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  fieldLabel: string;
  options: string[];
  names: string[];
  confirmLabel: string;
  onConfirm: (value: string) => Promise<unknown>;
  isPending: boolean;
  /** Placeholder and required-field error, when "Choose a <label>" does not read as English (e.g. "Extend by"). */
  prompt?: string;
  /** Consequence that applies to only some of the selection, shown above the list. */
  notice?: React.ReactNode;
  destructive?: boolean;
}) {
  const ask = prompt ?? `Choose a ${fieldLabel.toLowerCase()}`;
  const [value, setValue] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setValue('');
      setError(null);
    }
  }, [open]);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={title}
      description={description}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            variant={destructive ? 'destructive' : 'default'}
            onClick={async () => {
              if (!value) return setError(`${ask}.`);
              try {
                await onConfirm(value);
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
      <div className="flex flex-col gap-4">
        <FormField id="bulk-field" label={fieldLabel} error={error ?? undefined}>
          <Select value={value} onValueChange={(v) => (setValue(v), setError(null))}>
            <SelectTrigger id="bulk-field" className="w-full" aria-invalid={!!error}>
              <SelectValue placeholder={ask} />
            </SelectTrigger>
            <SelectContent>
              {options.map((o) => (
                <SelectItem key={o} value={o}>
                  {o}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {notice && (
          <Alert>
            <AlertTriangle />
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-medium text-muted-foreground">Applies to {names.length} selected</p>
          <SelectedList names={names} />
        </div>
      </div>
    </DialogShell>
  );
}

/** Plain confirm for reversible bulk actions (pause, disable, sync) that still deserve a second look. */
export function BulkConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  names,
  confirmLabel,
  onConfirm,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  names: string[];
  confirmLabel: string;
  onConfirm: () => Promise<unknown>;
  isPending: boolean;
}) {
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="sm"
      title={title}
      description={description}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            onClick={async () => {
              await onConfirm();
              onOpenChange(false);
            }}
          >
            {confirmLabel}
          </LoadingButton>
        </div>
      }
    >
      <SelectedList names={names} />
    </DialogShell>
  );
}
