'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { FormField } from '@/components/shared/form-field';
import { FormShell } from '@/components/shared/setting/form-shell';
import { Combobox } from '@/components/shared/setting/pickers';
import { Input } from '@/components/ui/input';
import { previewStore } from '@/lib/settings-preview-store';

const PROVIDERS = [
  { value: 'Harbor & Pine OpenAI', label: 'Harbor & Pine OpenAI', hint: 'openai' },
  { value: 'Harbor & Pine Anthropic', label: 'Harbor & Pine Anthropic', hint: 'anthropic' },
];
const CLEARANCE = [
  { value: 'Internal', label: 'Internal' },
  { value: 'Confidential', label: 'Confidential' },
  { value: 'Restricted', label: 'Restricted' },
];

/**
 * Create a model alias (S43). The same component is the Aliases section of Govern › Models (`shell="card"`) and the
 * "Model alias" dialog an agent’s Settings tab opens from its model picker (`shell="dialog"`).
 */
export function ModelAliasForm({ shell, open, onOpenChange, locked, onAdded }: { shell: 'card' | 'dialog'; open?: boolean; onOpenChange?: (o: boolean) => void; locked?: boolean; onAdded?: (alias: string) => void }) {
  const [alias, setAlias] = React.useState('');
  const [provider, setProvider] = React.useState<string | null>(null);
  const [model, setModel] = React.useState('');
  const [clearance, setClearance] = React.useState<string | null>('Internal');
  const [error, setError] = React.useState<string>();
  React.useEffect(() => {
    if (open) (setAlias(''), setProvider(null), setModel(''), setClearance('Internal'), setError(undefined));
  }, [open]);
  const submit = () => {
    if (!/^[a-z][a-z0-9-]*$/.test(alias) || !provider || !model.trim()) return setError('Give the alias a lower case name, a provider and a model.');
    previewStore.addAlias(alias, provider, model.trim(), clearance ?? 'Internal');
    toast.success(`Created ${alias}`, { description: 'Agents can pick it now. Design mock: nothing is stored.' });
    setAlias('');
    setModel('');
    setError(undefined);
    onOpenChange?.(false);
    onAdded?.(alias);
  };
  return (
    <FormShell shell={shell} id="alias-add" open={open} onOpenChange={onOpenChange} title="Model alias" description="An alias is the name an agent picks; the model behind it can change without editing the agent." submitLabel="Create alias" onSubmit={submit} locked={locked} requiredRole="Admin" help={error ? <span className="text-destructive">{error}</span> : 'The clearance is the most sensitive data the model may see.'}>
      <FormField id="alias-name" label="Alias">
        <Input id="alias-name" value={alias} onChange={(e) => (setAlias(e.target.value), setError(undefined))} placeholder="e.g. advisor-default" className="bg-card font-mono text-sm" autoComplete="off" />
      </FormField>
      <FormField id="alias-provider" label="Provider">
        <Combobox id="alias-provider" options={PROVIDERS} value={provider} onChange={setProvider} noun="providers" />
      </FormField>
      <FormField id="alias-model" label="Model">
        <Input id="alias-model" value={model} onChange={(e) => (setModel(e.target.value), setError(undefined))} placeholder="e.g. gpt-5.1" className="bg-card font-mono text-sm" autoComplete="off" />
      </FormField>
      <FormField id="alias-clearance" label="Cleared for">
        <Combobox options={CLEARANCE} value={clearance} onChange={setClearance} noun="levels" />
      </FormField>
    </FormShell>
  );
}
