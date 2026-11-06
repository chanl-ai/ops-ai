'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { RoleInput, RoleSummary } from '@/lib/types/settings';

const NOTHING = '__nothing__';

/**
 * Creates a custom role, empty or as a copy of another role (`copyOf` preselects it), or renames one (`role` set).
 * Enter saves; a name the workspace already uses shows under the name.
 */
export function RoleDialog({
  open,
  onOpenChange,
  roles,
  role,
  copyOf,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Every role of the workspace, the choices to copy from. */
  roles: RoleSummary[];
  /** The custom role to rename; unset makes a new one. */
  role?: RoleSummary | null;
  copyOf?: string | null;
  pending: boolean;
  onSubmit: (input: RoleInput) => Promise<unknown>;
}) {
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [source, setSource] = React.useState(NOTHING);
  const [errors, setErrors] = React.useState<{ name?: string; form?: string }>({});
  React.useEffect(() => {
    if (!open) return;
    const from = roles.find((r) => r.id === copyOf);
    setName(role?.name ?? (from ? `${from.name} copy` : ''));
    setDescription(role?.description ?? '');
    setSource(copyOf ?? NOTHING);
    setErrors({});
  }, [open, role, copyOf, roles]);

  const submit = async () => {
    if (!name.trim()) {
      setErrors({ name: 'Name the role.' });
      return;
    }
    try {
      await onSubmit({ name: name.trim(), description: description.trim(), ...(role ? {} : { copyOf: source === NOTHING ? null : source }) });
      onOpenChange(false);
    } catch (e) {
      const message = (e as Error).message;
      setErrors(/name/i.test(message) ? { name: message } : { form: message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !pending && onOpenChange(o)}
      size="md"
      title={role ? `Rename ${role.name}` : 'Create role'}
      description={
        role
          ? 'Everyone who holds the role keeps it under the new name.'
          : 'A role is a set of permissions you give people in a team. Start from nothing, or copy a role and change it. Secrets, egress and Security-team permissions come only with a built-in role.'
      }
      onSubmit={() => void submit()}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-destructive-text">{errors.form ?? ''}</p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={pending} loadingText="Saving…" data-testid="role-dialog-submit">
              {role ? 'Rename role' : 'Create role'}
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="role-name" label="Name" error={errors.name} hint="Unique in this workspace.">
          <Input id="role-name" value={name} maxLength={80} aria-invalid={!!errors.name} onChange={(e) => (setName(e.target.value), setErrors({}))} placeholder="e.g. Case desk" />
        </FormField>
        <FormField id="role-description" label="What it is for" optional>
          <Textarea id="role-description" value={description} maxLength={500} rows={2} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Works cases; changes nothing else" />
        </FormField>
        {!role && (
          <FormField id="role-source" label="Start from" hint="A copy leaves out the permissions a custom role cannot hold.">
            <Select value={source} onValueChange={setSource}>
              <SelectTrigger id="role-source" data-testid="role-source">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NOTHING}>No permissions</SelectItem>
                {roles.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    A copy of {r.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
      </div>
    </DialogShell>
  );
}
