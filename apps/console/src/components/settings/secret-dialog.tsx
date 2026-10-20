'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField, FormFieldGroup } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { useCreateSecret, useRotateSecret } from '@/hooks/secrets-queries';
import { useTeam } from '@/hooks/use-team';
import type { SecretMeta } from '@/lib/types/secrets';

/** Chips drawn in the Used by cell before "and N more"; a secret read by ten operations would otherwise make a row ten chips tall. */
export const USED_BY_SHOWN = 3;
export const usersText = (s: SecretMeta) => {
  const names = s.usedBy.map((u) => u.operation);
  return names.length > USED_BY_SHOWN ? `${names.slice(0, USED_BY_SHOWN).join(', ')} and ${names.length - USED_BY_SHOWN} more` : names.join(', ');
};

/** Which teams' tool modules may read a secret; none ticked is every team, as the gateway reads it. */
export function TeamsField({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { teams } = useTeam();
  return (
    <FormFieldGroup label="Teams" optional hint="Only these teams' tool modules may read it; the gateway refuses the rest. None ticked is every team.">
      {teams.map((t) => (
        <label key={t.id} className="flex items-center gap-2 text-sm">
          <Checkbox checked={value.includes(t.id)} onCheckedChange={(on) => onChange(on ? [...value, t.id] : value.filter((x) => x !== t.id))} aria-label={t.name} />
          {t.name}
        </label>
      ))}
    </FormFieldGroup>
  );
}

/** Create (no `rotating`) or rotate one secret. The value field is write-only and cleared on every open. */
export function SecretDialog({ open, rotating, onOpenChange, onSaved }: { open: boolean; rotating: SecretMeta | null; onOpenChange: (open: boolean) => void; /** Called with the name once a new secret is saved, so a picker can use it. */ onSaved?: (name: string) => void }) {
  const create = useCreateSecret();
  const rotate = useRotateSecret();
  const [name, setName] = React.useState('');
  const [value, setValue] = React.useState('');
  const [teams, setTeams] = React.useState<string[]>([]);
  const [errors, setErrors] = React.useState<{ name?: string; value?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) (setName(''), setValue(''), setTeams([]), setErrors({}));
  }, [open]);
  const pending = create.isPending || rotate.isPending;
  const submit = async () => {
    const e = { name: rotating || /^[A-Z][A-Z0-9_]*$/.test(name) ? undefined : 'Upper case letters, digits and underscores, starting with a letter.', value: value ? undefined : 'Enter the value.' };
    setErrors(e);
    if (e.name || e.value) return;
    try {
      const saved = rotating ? await rotate.mutateAsync({ name: rotating.name, value }) : await create.mutateAsync({ name, value, teams: teams.length ? teams : null });
      setValue('');
      toast.success(rotating ? `Rotated ${rotating.name}` : `Saved ${(saved as SecretMeta).name}`, { description: rotating ? 'The next call sends the new value.' : `Reference it in a header as {{${(saved as SecretMeta).name}}}.` });
      if (!rotating) onSaved?.((saved as SecretMeta).name);
      onOpenChange(false);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };
  return (
    <DialogShell
      open={open}
      onSubmit={submit}
      onOpenChange={onOpenChange}
      title={rotating ? `Rotate ${rotating.name}` : 'Add a secret'}
      description="The value is encrypted when saved and never shown again, here or anywhere else."
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={pending} loadingText="Saving…" data-testid="secret-submit">
            {rotating ? 'Rotate' : 'Save secret'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {!rotating && (
          <FormField id="secret-name" label="Name" error={errors.name} hint="Headers reference it as {{NAME}}.">
            <Input id="secret-name" value={name} aria-invalid={!!errors.name} onChange={(e) => (setName(e.target.value.toUpperCase()), setErrors({}))} placeholder="e.g. STATEMENTS_KEY" className="font-mono text-sm" autoComplete="off" />
          </FormField>
        )}
        <FormField id="secret-value" label={rotating ? 'New value' : 'Value'} error={errors.value ?? errors.submit}>
          <Input id="secret-value" type="password" value={value} aria-invalid={!!(errors.value ?? errors.submit)} onChange={(e) => (setValue(e.target.value), setErrors({}))} autoComplete="new-password" />
        </FormField>
        {!rotating && <TeamsField value={teams} onChange={setTeams} />}
        {rotating && rotating.usedBy.length > 0 && <p className="text-xs text-muted-foreground">The next call of {usersText(rotating)} sends the new value.</p>}
      </div>
    </DialogShell>
  );
}

