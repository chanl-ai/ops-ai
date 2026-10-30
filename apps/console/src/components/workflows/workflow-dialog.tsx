'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/** Name the workflow and say what starts it; the draft opens on the canvas with a request trigger and an end. */
export function WorkflowDialog({
  open,
  onOpenChange,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (input: { name: string; trigger: string }) => Promise<unknown>;
  isPending: boolean;
}) {
  const [values, setValues] = React.useState({ name: '', trigger: '' });
  const [errors, setErrors] = React.useState<{ name?: string; trigger?: string }>({});
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setValues({ name: '', trigger: '' });
      setErrors({});
      setSubmitError(null);
    }
  }, [open]);

  const submit = async () => {
    const e = { name: values.name.trim() ? undefined : 'Name the workflow.', trigger: values.trigger.trim() ? undefined : 'Say what starts a run.' };
    setErrors(e);
    if (e.name || e.trigger) return;
    try {
      // The page navigates to the new workflow; closing here would replace that URL with the list's.
      await onSubmit(values);
    } catch (err) {
      setSubmitError((err as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="New workflow"
      description="Creates a draft and opens it on the canvas. Nothing runs until you publish."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={isPending} loadingText="Creating…">
            Create and open
          </LoadingButton>
        </div>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {submitError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{submitError}</p>}
        <FormField id="wf-name" label="Name" error={errors.name}>
          <Input id="wf-name" value={values.name} onChange={(e) => (setValues((v) => ({ ...v, name: e.target.value })), setErrors((x) => ({ ...x, name: undefined })))} placeholder="e.g. Overdraft fee refund" aria-invalid={!!errors.name} />
        </FormField>
        <FormField id="wf-trigger" label="Starts when" error={errors.trigger} hint="Plain language is fine; you will wire the trigger on the canvas.">
          <Input id="wf-trigger" value={values.trigger} onChange={(e) => (setValues((v) => ({ ...v, trigger: e.target.value })), setErrors((x) => ({ ...x, trigger: undefined })))} placeholder="e.g. Customer requests a fee refund" aria-invalid={!!errors.trigger} />
        </FormField>
      </form>
    </DialogShell>
  );
}
