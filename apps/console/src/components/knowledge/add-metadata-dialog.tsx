'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { Item } from '@/lib/types/knowledge';

const HINT: Record<string, string> = {
  effective_date: 'The date it took effect, such as 2026-07-01.',
  jurisdiction: 'e.g. CA for bank-wide, or ON, QC, BC, AB',
  product: 'e.g. credit_card, personal_loan, cards',
  owner: 'The person or team that answers for this document.',
};
const PLACEHOLDER: Record<string, string> = { jurisdiction: 'e.g. CA', product: 'e.g. cards', owner: 'e.g. Card Services' };

/** Supplies the metadata a held item is missing, so the knowledge bases that require it can search it. */
export function AddMetadataDialog({ item, open, onOpenChange, isPending, onSubmit }: { item?: Pick<Item, 'title' | 'held'>; open: boolean; onOpenChange: (o: boolean) => void; isPending: boolean; onSubmit: (values: Record<string, string>) => Promise<unknown> }) {
  const missing = item?.held?.missing ?? [];
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setValues({});
      setError(null);
    }
  }, [open]);
  const blank = missing.filter((k) => !values[k]?.trim());
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={`Add metadata to ${item?.title ?? 'this item'}`}
      description={item?.held ? `Held by ${item.held.kbNames.join(', ')} until these are set. The values are logged with your name; the next sync keeps them unless the source sends its own.` : undefined}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            disabled={blank.length > 0}
            onClick={async () => {
              try {
                await onSubmit(values);
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Save and release
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {error && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
        {missing.map((k) => (
          <FormField key={k} id={`md-${k}`} label={k.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())} hint={HINT[k]}>
            <Input id={`md-${k}`} type={k === 'effective_date' ? 'date' : 'text'} value={values[k] ?? ''} onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))} placeholder={k === 'effective_date' ? undefined : (PLACEHOLDER[k] ?? 'e.g. a value')} />
          </FormField>
        ))}
      </div>
    </DialogShell>
  );
}
