'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAddEgress } from '@/hooks/egress-queries';
import type { EgressKind } from '@/lib/types/egress';

export const EGRESS_COPY = {
  host: { noun: 'host', label: 'Host', placeholder: 'e.g. api.bank.example', hint: 'A DNS name. Tool calls go to it over https on 443 only.' },
  range: { noun: 'private range', label: 'Range', placeholder: 'e.g. 10.20.0.0/16', hint: 'A listed host may resolve into this range. Loopback, link-local and cloud metadata can never be listed.' },
} as const;

/**
 * Adds a host or private range to the egress allowlist: the Egress settings page's form, also opened in place from a
 * tool whose request goes to a host that is not listed (c-517), so the same form and the same audit serve both.
 */
export function EgressAddDialog({
  kind,
  onOpenChange,
  preset = '',
}: {
  kind: EgressKind | null;
  onOpenChange: (open: boolean) => void;
  /** The value the form opens with: the host a tool calls, when opened from that tool. */ preset?: string;
}) {
  const add = useAddEgress();
  const [value, setValue] = React.useState('');
  const [note, setNote] = React.useState('');
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (kind) (setValue(preset), setNote(''), setError(undefined));
  }, [kind, preset]);
  const copy = EGRESS_COPY[kind ?? 'host'];
  const submit = async () => {
    if (!value.trim()) return setError(`Enter a ${copy.noun}.`);
    try {
      const r = await add.mutateAsync({ kind: kind!, value: value.trim(), note });
      toast.success(r.changed ? `Listed ${r.value}` : `${r.value} was already listed`);
      onOpenChange(false);
    } catch (e) {
      // The service names why a value can never be listed (400); show that, not a generic failure.
      setError((e as Error).message);
    }
  };
  return (
    <DialogShell
      open={!!kind}
      onSubmit={submit}
      onOpenChange={onOpenChange}
      title={`Add a ${copy.noun}`}
      description="Every change is audited."
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={add.isPending} loadingText="Adding…" data-testid="egress-add-submit">
            Add {copy.noun}
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="egress-value" label={copy.label} error={error} hint={copy.hint}>
          <Input
            id="egress-value"
            value={value}
            aria-invalid={!!error}
            onChange={(e) => (setValue(e.target.value), setError(undefined))}
            placeholder={copy.placeholder}
            className="font-mono text-sm"
          />
        </FormField>
        <FormField id="egress-note" label="Note" optional hint="Why this is listed, for whoever reviews the list next.">
          <Input id="egress-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Core banking statements API" />
        </FormField>
      </div>
    </DialogShell>
  );
}
