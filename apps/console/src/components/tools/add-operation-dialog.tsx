'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import type { HttpOperationInput } from '@/lib/types/tool-modules';

import { HttpOperationBuilder } from './http-operation-builder';

const EMPTY: HttpOperationInput = { name: '', description: '', access: 'read', method: 'GET', url: '', headers: [{ key: 'Accept', value: 'application/json' }], body: '' };

/** One operation built by hand on the module page: method, URL, headers and body. Works for every module type. */
export function AddOperationDialog({ open, onOpenChange, onAdd, adding }: { open: boolean; onOpenChange: (o: boolean) => void; onAdd: (input: HttpOperationInput) => Promise<void>; adding: boolean }) {
  const [value, setValue] = React.useState<HttpOperationInput>(EMPTY);
  const [touched, setTouched] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setValue(EMPTY);
    setTouched(false);
    setError(null);
  }, [open]);
  const errors = touched ? { name: /^[a-z][a-z0-9_]{2,}$/.test(value.name) ? undefined : 'Use lower case letters, digits and underscores.', url: /^https:\/\/[^\s]+$/.test(value.url) ? undefined : 'Enter the full https URL.' } : undefined;

  const submit = async () => {
    setTouched(true);
    if (!/^[a-z][a-z0-9_]{2,}$/.test(value.name) || !/^https:\/\/[^\s]+$/.test(value.url)) return;
    try {
      await onAdd(value);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onSubmit={submit}
      onOpenChange={onOpenChange}
      size="md"
      title="Add operation"
      description="Added to the draft. A published module stages it for the next version."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={adding}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={adding} loadingText="Adding…" data-testid="add-operation-save">
            Add operation
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-testid="add-operation-dialog">
        {error && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
        <HttpOperationBuilder value={value} onChange={setValue} errors={errors} />
      </div>
    </DialogShell>
  );
}
