'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { ModuleDetailsPatch } from '@/lib/types/tool-modules';

/** The module's display name and description. Its module name stays: workflows pin it. */
export function EditModuleDialog({
  open,
  onOpenChange,
  displayName: initialName,
  description: initialDescription,
  moduleName,
  onSave,
  saving,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  displayName: string;
  description: string;
  moduleName: string;
  onSave: (patch: ModuleDetailsPatch) => Promise<void>;
  saving: boolean;
}) {
  const [displayName, setDisplayName] = React.useState(initialName);
  const [description, setDescription] = React.useState(initialDescription);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setDisplayName(initialName);
    setDescription(initialDescription);
    setError(null);
  }, [open, initialName, initialDescription]);

  const submit = async () => {
    if (!displayName.trim()) return setError('Give the module a display name.');
    try {
      await onSave({ displayName: displayName.trim(), description: description.trim() });
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Edit details"
      description={`Module name ${moduleName} stays the same; workflows pin it.`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <LoadingButton isLoading={saving} loadingText="Saving…" onClick={submit} data-testid="edit-module-save">
            Save
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="em-display" label="Display name" error={error ?? undefined}>
          <Input id="em-display" autoFocus value={displayName} aria-invalid={!!error} onChange={(e) => (setDisplayName(e.target.value), setError(null))} placeholder="e.g. Document service" />
        </FormField>
        <FormField id="em-desc" label="Description" optional>
          <Textarea id="em-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Fetches signed loan documents for the lending inbox" className="min-h-20 resize-none" />
        </FormField>
      </div>
    </DialogShell>
  );
}
