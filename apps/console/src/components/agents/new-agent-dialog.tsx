'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { AgentInput, ModelAlias } from '@/lib/types/domain';

import { modelHint, ModelSelect } from './model-select';

/**
 * Blank agent in one screen: name, a one-line role and the model. It saves as a draft and the agent page does the
 * rest (instructions, tools, knowledge, skills, guardrails). Templates are the second button on the list page.
 */
export function NewAgentDialog({
  open,
  onOpenChange,
  models,
  team,
  isPending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  models: ModelAlias[];
  /** The owning team the agent is created under; changeable on the agent page. */
  /** The current team's name; the server makes the agent that team's from the person's token. */
  team: string;
  isPending: boolean;
  onSubmit: (input: AgentInput) => Promise<unknown>;
}) {
  const [name, setName] = React.useState('');
  const [role, setRole] = React.useState('');
  const [model, setModel] = React.useState('');
  const [errors, setErrors] = React.useState<{ name?: string; role?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) {
      setName('');
      setRole('');
      setModel('');
      setErrors({});
    }
  }, [open]);
  const chosenModel = model || models[0]?.name || '';

  const submit = async () => {
    const e = { name: name.trim().length >= 2 ? undefined : 'Name the agent in 2 to 80 characters.', role: role.trim() ? undefined : 'Say in one line what the agent does.' };
    setErrors(e);
    if (e.name || e.role) return;
    try {
      await onSubmit({ name: name.trim(), role: role.trim(), model: chosenModel, channels: ['chat'] });
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="New agent"
      description={`Starts as a draft owned by ${team || 'your team'}. Write the instructions and grant tools on the next page.`}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {errors.submit && <p className="mr-auto text-xs text-destructive">{errors.submit}</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton isLoading={isPending} onClick={submit} data-testid="new-agent-submit">
            Create agent
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="na-name" label="Name" error={errors.name}>
          <Input id="na-name" aria-invalid={!!errors.name} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Statement Request Helper" maxLength={80} />
        </FormField>
        <FormField id="na-role" label="Role" error={errors.role} hint="One line. The instructions come next, on the agent page.">
          <Input id="na-role" aria-invalid={!!errors.role} value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Answers statement copy requests from the servicing mailbox" />
        </FormField>
        <FormField id="na-model" label="Model" hint={modelHint(models, chosenModel)}>
          <ModelSelect id="na-model" value={chosenModel} onValueChange={setModel} aliases={models} />
        </FormField>
      </div>
    </DialogShell>
  );
}
