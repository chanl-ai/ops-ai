'use client';

import * as React from 'react';
import { GitBranch, Square, UserCheck } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import type { WorkflowInput } from '@/lib/types/domain';

const TEMPLATES: { value: WorkflowInput['template']; label: string; description: string; icon: typeof Square }[] = [
  { value: 'approval', label: 'Agent with approval', description: 'Trigger, agent step, one review gate, action.', icon: UserCheck },
  { value: 'triage', label: 'Triage and route', description: 'An AI router sends each case to the right branch.', icon: GitBranch },
  { value: 'blank', label: 'Blank', description: 'Only a trigger. Build the rest on the canvas.', icon: Square },
];

/** Name the workflow and pick a starting shape; the canvas does the rest. */
export function WorkflowDialog({
  open,
  onOpenChange,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (input: WorkflowInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [values, setValues] = React.useState<WorkflowInput>({ name: '', trigger: '', template: 'approval' });
  const [errors, setErrors] = React.useState<{ name?: string; trigger?: string }>({});
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) {
      setValues({ name: '', trigger: '', template: 'approval' });
      setErrors({});
      setSubmitError(null);
    }
  }, [open]);

  const submit = async () => {
    const e = { name: values.name.trim() ? undefined : 'Name the workflow.', trigger: values.trigger.trim() ? undefined : 'Say what starts a run.' };
    setErrors(e);
    if (e.name || e.trigger) return;
    try {
      await onSubmit(values);
      onOpenChange(false);
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
        <FormField id="wf-trigger" label="Starts when" error={errors.trigger} hint="Plain language is fine; you will wire the trigger node on the canvas.">
          <Input id="wf-trigger" value={values.trigger} onChange={(e) => (setValues((v) => ({ ...v, trigger: e.target.value })), setErrors((x) => ({ ...x, trigger: undefined })))} placeholder="e.g. Customer requests a fee refund" aria-invalid={!!errors.trigger} />
        </FormField>
        <FormField id="wf-template" label="Start from">
          <RadioGroup id="wf-template" value={values.template} onValueChange={(t) => setValues((v) => ({ ...v, template: t as WorkflowInput['template'] }))} className="gap-2">
            {TEMPLATES.map((t) => (
              <label key={t.value} htmlFor={`tpl-${t.value}`} className="flex cursor-pointer items-start gap-3 rounded-lg border p-3 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5">
                <RadioGroupItem id={`tpl-${t.value}`} value={t.value} className="mt-0.5" />
                <t.icon className="mt-0.5 size-4 text-muted-foreground" />
                <span>
                  <span className="block text-sm font-medium">{t.label}</span>
                  <span className="block text-xs text-muted-foreground">{t.description}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
        </FormField>
      </form>
    </DialogShell>
  );
}
