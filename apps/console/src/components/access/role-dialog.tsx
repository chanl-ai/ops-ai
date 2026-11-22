'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { RoleSelect } from '@/components/access/role-select';
import { rolesWhere } from '@/hooks/me-queries';
import { useOptionLabels } from '@/hooks/options-queries';
import type { RoleInput, RoleSummary } from '@/lib/types/settings';
import { nameError } from '@/lib/validation/names';

const NOTHING = '__nothing__';
/** Every role of the workspace, the choices to copy from; searched on the server. */
const allRoles = rolesWhere('role-copy-options');

/**
 * Creates a custom role, empty or as a copy of another role (`copyOf` preselects it), or renames one (`role` set).
 * Enter saves; a name the workspace already uses shows under the name.
 */
export function RoleDialog({
  open,
  onOpenChange,
  role,
  copyOf,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
    setName(role?.name ?? '');
    setDescription(role?.description ?? '');
    setSource(copyOf ?? NOTHING);
    setErrors({});
  }, [open, role, copyOf]);
  // A copy starts under its source's name, until the person types their own.
  const copyName = useOptionLabels(allRoles, open && !role && source !== NOTHING ? [source] : []).data?.data[0]?.label;
  React.useEffect(() => {
    if (copyName) setName((prev) => (!prev || prev.endsWith(' copy') ? `${copyName} copy` : prev));
  }, [copyName]);

  const submit = async () => {
    const nameIssue = nameError(name, 'Name the role.');
    if (nameIssue) {
      setErrors({ name: nameIssue });
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
            <RoleSelect source={allRoles} value={source === NOTHING ? '' : source} onChange={(id) => setSource(id || NOTHING)} placeholder="No permissions" noneLabel="No permissions" prefix="A copy of " testId="role-source" className="w-full" />
          </FormField>
        )}
      </div>
    </DialogShell>
  );
}
