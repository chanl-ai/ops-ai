'use client';

import * as React from 'react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { Workflow, WorkflowSettingsInput } from '@/lib/types/domain';

/** Workflow identity, edited in place (revisitable config belongs on the page, not in a dialog). */
export function WorkflowSettingsForm({
  workflow,
  owners,
  onSave,
  isSaving,
}: {
  workflow: Workflow;
  owners: string[];
  onSave: (input: WorkflowSettingsInput) => Promise<unknown>;
  isSaving: boolean;
}) {
  const initial = React.useMemo(() => ({ name: workflow.name, description: workflow.description, owner: workflow.owner, trigger: workflow.trigger }), [workflow]);
  const [v, setV] = React.useState<WorkflowSettingsInput>(initial);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    setV(initial);
  }, [initial]);
  const dirty = JSON.stringify(v) !== JSON.stringify(initial);
  const set = <K extends keyof WorkflowSettingsInput>(k: K, val: WorkflowSettingsInput[K]) => (setV((s) => ({ ...s, [k]: val })), setError(null));

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={async (e) => {
        e.preventDefault();
        if (!v.name.trim()) return setError('The workflow needs a name.');
        await onSave(v);
      }}
    >
      <SettingsSection title="Details" description="Shown in lists, on every review this workflow raises, and in the audit log.">
        <div className="grid gap-4 md:grid-cols-2">
          <FormField id="wf-set-name" label="Name" error={error ?? undefined}>
            <Input id="wf-set-name" value={v.name} onChange={(e) => set('name', e.target.value)} className="bg-card" aria-invalid={!!error} />
          </FormField>
          <FormField id="wf-set-owner" label="Owning team">
            <Select value={v.owner} onValueChange={(o) => set('owner', o)}>
              <SelectTrigger id="wf-set-owner" className="w-full bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {owners.map((o) => (
                  <SelectItem key={o} value={o}>
                    {o}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="wf-set-trigger" label="Starts when" className="md:col-span-2">
            <Input id="wf-set-trigger" value={v.trigger} onChange={(e) => set('trigger', e.target.value)} className="bg-card" />
          </FormField>
          <FormField id="wf-set-desc" label="Description" optional className="md:col-span-2">
            <Textarea id="wf-set-desc" value={v.description} onChange={(e) => set('description', e.target.value)} className="min-h-20 bg-card" />
          </FormField>
        </div>
      </SettingsSection>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" disabled={!dirty || isSaving} onClick={() => setV(initial)}>
          Discard
        </Button>
        <LoadingButton type="submit" disabled={!dirty} isLoading={isSaving} loadingText="Saving…">
          Save settings
        </LoadingButton>
      </div>
    </form>
  );
}
