'use client';

import * as React from 'react';

import { CHANNEL_ICON } from '@/components/agents/agent-card';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { Lookups } from '@/lib/api';
import type { Agent, AgentInput, Channel } from '@/lib/types/domain';

const CHANNELS: Channel[] = ['voice', 'chat', 'email', 'api'];
const EMPTY: AgentInput = { name: '', role: '', model: '', owner: '', channels: ['chat'], instructions: '' };
type Errors = Partial<Record<keyof AgentInput, string>>;

function validate(v: AgentInput): Errors {
  const e: Errors = {};
  if (!v.name.trim()) e.name = 'Give the agent a name.';
  if (!v.role.trim()) e.role = 'Describe the job in one line; reviewers see it on every paused run.';
  if (!v.model) e.model = 'Choose a model.';
  if (!v.owner) e.owner = 'Choose the team that owns this agent.';
  if (!v.channels.length) e.channels = 'Pick at least one channel.';
  return e;
}

const slugPreview = (name: string) =>
  name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');

/** Create or edit an agent's identity. Tools and knowledge are granted on the agent page, not here. */
export function AgentDialog({
  open,
  onOpenChange,
  agent,
  lookups,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agent?: Agent | null;
  lookups?: Lookups;
  onSubmit: (input: AgentInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [values, setValues] = React.useState<AgentInput>(EMPTY);
  const [errors, setErrors] = React.useState<Errors>({});
  const [submitError, setSubmitError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setValues(agent ? { name: agent.name, role: agent.role, model: agent.model, owner: agent.owner, channels: agent.channels, instructions: agent.instructions } : EMPTY);
    setErrors({});
    setSubmitError(null);
  }, [open, agent]);

  const set = <K extends keyof AgentInput>(k: K, v: AgentInput[K]) => {
    setValues((s) => ({ ...s, [k]: v }));
    setErrors((e) => ({ ...e, [k]: undefined }));
  };

  const submit = async () => {
    const e = validate(values);
    setErrors(e);
    if (Object.keys(e).length) return;
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
      title={agent ? `Edit ${agent.name}` : 'Create agent'}
      description={agent ? 'Saves a new version. Workflows adopt it when they are republished.' : 'Set tools, knowledge and guardrails on the next page, then add it to a workflow.'}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={isPending} loadingText="Saving…">
            {agent ? 'Save changes' : 'Create draft'}
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
        <FormField
          id="agent-name"
          label="Name"
          error={errors.name}
          hint={!agent && values.name ? <>Handle: <code className="font-mono">{slugPreview(values.name)}</code></> : undefined}
        >
          <Input id="agent-name" value={values.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Overdraft Helper" aria-invalid={!!errors.name} />
        </FormField>
        <FormField id="agent-role" label="Job" error={errors.role}>
          <Input id="agent-role" value={values.role} onChange={(e) => set('role', e.target.value)} placeholder="e.g. Explains overdraft fees and books callbacks" aria-invalid={!!errors.role} />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="agent-model" label="Model" error={errors.model}>
            <Select value={values.model} onValueChange={(v) => set('model', v)}>
              <SelectTrigger id="agent-model" className="w-full font-mono text-xs" aria-invalid={!!errors.model}>
                <SelectValue placeholder="Choose a model" />
              </SelectTrigger>
              <SelectContent>
                {lookups?.models.map((m) => (
                  <SelectItem key={m} value={m} className="font-mono text-xs">
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="agent-owner" label="Owning team" error={errors.owner}>
            <Select value={values.owner} onValueChange={(v) => set('owner', v)}>
              <SelectTrigger id="agent-owner" className="w-full" aria-invalid={!!errors.owner}>
                <SelectValue placeholder="Choose a team" />
              </SelectTrigger>
              <SelectContent>
                {lookups?.owners.map((o) => (
                  <SelectItem key={o} value={o}>
                    {o}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <FormField id="agent-channels" label="Channels" error={errors.channels}>
          <ToggleGroup
            id="agent-channels"
            type="multiple"
            variant="outline"
            value={values.channels}
            onValueChange={(v) => set('channels', v as Channel[])}
            className="w-full"
          >
            {CHANNELS.map((c) => {
              const Icon = CHANNEL_ICON[c];
              return (
                <ToggleGroupItem key={c} value={c} className="flex-1" aria-label={c}>
                  <Icon className="size-3.5" /> {c === 'api' ? 'API' : c[0].toUpperCase() + c.slice(1)}
                </ToggleGroupItem>
              );
            })}
          </ToggleGroup>
        </FormField>
        <FormField id="agent-instructions" label="Instructions" optional hint="What the agent must always and never do. You can refine this later.">
          <Textarea id="agent-instructions" value={values.instructions} onChange={(e) => set('instructions', e.target.value)} className="min-h-24" />
        </FormField>
      </form>
    </DialogShell>
  );
}
