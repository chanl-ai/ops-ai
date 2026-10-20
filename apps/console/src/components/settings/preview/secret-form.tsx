'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { FormField } from '@/components/shared/form-field';
import { FormShell } from '@/components/shared/setting/form-shell';
import { MultiSelect } from '@/components/shared/setting/pickers';
import { Input } from '@/components/ui/input';
import { previewStore } from '@/lib/settings-preview-store';

export const TEAM_OPTIONS = [
  { value: 'Operations', label: 'Operations' },
  { value: 'Lending', label: 'Lending' },
  { value: 'Fraud', label: 'Fraud' },
  { value: 'Security', label: 'Security' },
];

/**
 * Add a secret (S17). The same component is the Secrets section of Govern › Security (`shell="card"`) and the "Add
 * secret" dialog a tool page opens when a header names a secret that does not exist (`shell="dialog"`).
 */
export function SecretForm({ shell, open, onOpenChange, locked, presetName }: { shell: 'card' | 'dialog'; open?: boolean; onOpenChange?: (o: boolean) => void; locked?: boolean; presetName?: string }) {
  const [name, setName] = React.useState(presetName ?? '');
  const [value, setValue] = React.useState('');
  const [teams, setTeams] = React.useState<string[]>([]);
  const [errors, setErrors] = React.useState<{ name?: string; value?: string }>({});
  React.useEffect(() => {
    if (open) (setName(presetName ?? ''), setValue(''), setTeams([]), setErrors({}));
  }, [open, presetName]);
  const submit = () => {
    const e = { name: /^[A-Z][A-Z0-9_]*$/.test(name) ? undefined : 'Upper case letters, digits and underscores, starting with a letter.', value: value ? undefined : 'Enter the value.' };
    setErrors(e);
    if (e.name || e.value) return;
    previewStore.addSecret(name, value, teams);
    toast.success(`Saved ${name}`, { description: `Reference it in a header as {{${name}}}. Design mock: nothing is stored.` });
    setName(presetName ?? '');
    setValue('');
    setTeams([]);
    onOpenChange?.(false);
  };
  return (
    <FormShell shell={shell} id="secret-add" open={open} onOpenChange={onOpenChange} title="Add secret" description="The value is encrypted when saved and never shown again, here or anywhere else." submitLabel="Save secret" onSubmit={submit} locked={locked} requiredRole="Security admin" help="Headers reference it as {{NAME}}.">
      <FormField id="secret-name" label="Name" error={errors.name}>
        <Input id="secret-name" value={name} onChange={(e) => (setName(e.target.value.toUpperCase()), setErrors({}))} placeholder="e.g. STATEMENTS_KEY" className="bg-card font-mono text-sm" autoComplete="off" aria-invalid={!!errors.name} />
      </FormField>
      <FormField id="secret-value" label="Value" error={errors.value}>
        <Input id="secret-value" type="password" value={value} onChange={(e) => (setValue(e.target.value), setErrors({}))} className="bg-card" autoComplete="new-password" aria-invalid={!!errors.value} />
      </FormField>
      <FormField id="secret-teams" label="Teams" optional hint="Only these teams’ tool modules may read it. None chosen is every team.">
        <MultiSelect options={TEAM_OPTIONS} value={teams} onChange={setTeams} noun="teams" />
      </FormField>
    </FormShell>
  );
}
