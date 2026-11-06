'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/**
 * Renames one thing: its name in a field, Save while the name is new and not empty. `description` says what reads the
 * name; `error` is the API's refusal, shown under the field.
 */
export function RenameDialog({
  name,
  description,
  busy,
  error,
  testId,
  onClose,
  onSave,
}: {
  name: string;
  description: string;
  busy: boolean;
  error?: string | null;
  testId: string;
  onClose: () => void;
  onSave: (name: string) => void;
}) {
  const [value, setValue] = React.useState(name);
  const next = value.trim();
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="sm"
      title={`Rename ${name}`}
      description={description}
      data-testid={testId}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton isLoading={busy} disabled={!next || next === name} onClick={() => onSave(next)} data-testid={`${testId}-save`}>
            Save
          </LoadingButton>
        </>
      }
    >
      <FormField id={`${testId}-name`} label="Name">
        <Input id={`${testId}-name`} value={value} onChange={(e) => setValue(e.target.value)} />
      </FormField>
      {error && (
        <p className="text-sm text-destructive-text" role="alert" data-testid={`${testId}-error`}>
          {error}
        </p>
      )}
    </DialogShell>
  );
}
