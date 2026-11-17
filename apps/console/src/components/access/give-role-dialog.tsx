'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { RoleSelect } from '@/components/access/role-select';
import { rolesWhere } from '@/hooks/me-queries';

/** The workspace's own roles; a built-in role comes with a person's team role. */
const customRoles = rolesWhere('role-give-options', [], { builtin: ['false'] });

/**
 * Gives a person one of the workspace's custom roles in the team the console acts in (switch team to give it in
 * another). A built-in role comes with their team role, so only custom roles are offered; the server's refusal (not
 * an admin of the team, not in the team, held already) shows here.
 */
export function GiveRoleDialog({
  open,
  onOpenChange,
  personName,
  teamName,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  personName: string;
  /** The team the console acts in, where the role is given. */
  teamName: string;
  pending: boolean;
  onSubmit: (input: { roleId: string }) => Promise<unknown>;
}) {
  const [roleId, setRoleId] = React.useState('');
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    if (!open) return;
    setRoleId('');
    setError('');
  }, [open]);

  const submit = async () => {
    if (!roleId) {
      setError('Choose the role.');
      return;
    }
    try {
      await onSubmit({ roleId });
      onOpenChange(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !pending && onOpenChange(o)}
      size="md"
      title={`Give ${personName} a role`}
      description={`In ${teamName}: the role adds what it allows there, on top of their team role, from their next action. To give it in another team, switch to that team first.`}
      onSubmit={() => void submit()}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-destructive-text">{error}</p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={pending} loadingText="Giving…" disabled={!roleId} data-testid="give-role-submit">
              Give role
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="give-role" label="Role" hint="The workspace’s own roles; a built-in role comes with their team role. Make one on Access › Roles.">
          <RoleSelect source={customRoles} value={roleId} onChange={(v) => (setRoleId(v), setError(''))} placeholder="Choose a role" testId="give-role-role" className="w-full" />
        </FormField>
      </div>
    </DialogShell>
  );
}
