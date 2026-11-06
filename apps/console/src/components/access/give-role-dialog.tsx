'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { RoleSummary } from '@/lib/types/settings';

/**
 * Gives a person one of the workspace's custom roles in the team the console acts in (switch team to give it in
 * another). A built-in role comes with their team role, so only custom roles are offered; the server's refusal (not
 * an admin of the team, not in the team, held already) shows here.
 */
export function GiveRoleDialog({
  open,
  onOpenChange,
  personName,
  roles,
  teamName,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  personName: string;
  /** Every role of the workspace; only the custom ones are offered. */
  roles: RoleSummary[];
  /** The team the console acts in, where the role is given. */
  teamName: string;
  pending: boolean;
  onSubmit: (input: { roleId: string }) => Promise<unknown>;
}) {
  const custom = roles.filter((r) => !r.builtin);
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
            <LoadingButton type="submit" isLoading={pending} loadingText="Giving…" disabled={!custom.length} data-testid="give-role-submit">
              Give role
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="give-role" label="Role" hint={custom.length ? 'The workspace’s own roles; a built-in role comes with their team role.' : 'No custom roles yet: create one on Access › Roles.'}>
          <Select value={roleId} onValueChange={(v) => (setRoleId(v), setError(''))} disabled={!custom.length}>
            <SelectTrigger id="give-role" data-testid="give-role-role">
              <SelectValue placeholder="Choose a role" />
            </SelectTrigger>
            <SelectContent>
              {custom.map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </div>
    </DialogShell>
  );
}
