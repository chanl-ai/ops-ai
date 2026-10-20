'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { WorkspaceTeam, WorkspaceTeamInput } from '@/lib/types/team';

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/**
 * Creates a team with its first admin, or renames one (`team` set). Enter saves; the server's refusal (a name the
 * workspace already uses, an email of nobody in the workspace) shows under the field it is about.
 */
export function TeamDialog({
  open,
  onOpenChange,
  team,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  team?: WorkspaceTeam | null;
  pending: boolean;
  onSubmit: (input: WorkspaceTeamInput) => Promise<unknown>;
}) {
  const [name, setName] = React.useState('');
  const [admin, setAdmin] = React.useState('');
  const [errors, setErrors] = React.useState<{ name?: string; admin?: string; form?: string }>({});
  React.useEffect(() => {
    if (!open) return;
    setName(team?.name ?? '');
    setAdmin('');
    setErrors({});
  }, [open, team]);

  const submit = async () => {
    const found = {
      name: name.trim() ? undefined : 'Name the team.',
      admin: team || EMAIL.test(admin.trim()) ? undefined : 'Enter the work email of the person who leads the team.',
    };
    setErrors(found);
    if (found.name || found.admin) return;
    try {
      await onSubmit({ name: name.trim(), admin: admin.trim() });
      onOpenChange(false);
    } catch (e) {
      const message = (e as Error).message;
      setErrors(/name/i.test(message) ? { name: message } : /person|email/i.test(message) ? { admin: message } : { form: message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !pending && onOpenChange(o)}
      size="md"
      title={team ? `Rename ${team.name}` : 'Create team'}
      description={team ? 'Everyone in the team sees the new name in the team switcher.' : 'A team owns its agents, workflows, tools, knowledge and secrets. Its first admin adds people and sets their roles.'}
      onSubmit={() => void submit()}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-destructive">{errors.form ?? ''}</p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={pending} loadingText="Saving…" data-testid="team-submit">
              {team ? 'Rename team' : 'Create team'}
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="team-name" label="Name" error={errors.name} hint="Unique in this workspace.">
          <Input id="team-name" value={name} maxLength={80} aria-invalid={!!errors.name} onChange={(e) => (setName(e.target.value), setErrors({}))} placeholder="e.g. Lending" />
        </FormField>
        {!team && (
          <FormField id="team-admin" label="First admin" error={errors.admin} hint="Someone who already has an account in this workspace.">
            <Input id="team-admin" type="email" value={admin} aria-invalid={!!errors.admin} onChange={(e) => (setAdmin(e.target.value), setErrors({}))} placeholder="e.g. name@northfieldbank.com" />
          </FormField>
        )}
      </div>
    </DialogShell>
  );
}
