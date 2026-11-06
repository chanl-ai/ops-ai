'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { RoleSummary } from '@/lib/types/settings';

/**
 * Gives a person one of the workspace's custom roles in one of their teams. A built-in role comes with their team
 * role, so only custom roles are offered; the server's refusal (not an admin of that team, held already) shows here.
 */
export function GiveRoleDialog({
  open,
  onOpenChange,
  personName,
  roles,
  teams,
  pending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  personName: string;
  /** Every role of the workspace; only the custom ones are offered. */
  roles: RoleSummary[];
  /** The person's teams. */
  teams: { teamId: string; teamName: string }[];
  pending: boolean;
  onSubmit: (input: { roleId: string; teamId: string }) => Promise<unknown>;
}) {
  const custom = roles.filter((r) => !r.builtin);
  const [roleId, setRoleId] = React.useState('');
  const [teamId, setTeamId] = React.useState('');
  const [error, setError] = React.useState('');
  React.useEffect(() => {
    if (!open) return;
    setRoleId('');
    setTeamId(teams.length === 1 ? teams[0].teamId : '');
    setError('');
  }, [open, teams]);

  const submit = async () => {
    if (!roleId || !teamId) {
      setError('Choose the role and the team.');
      return;
    }
    try {
      await onSubmit({ roleId, teamId });
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
      description="A role adds what it allows in one team, on top of their team role. It applies on their next action."
      onSubmit={() => void submit()}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-destructive">{error}</p>
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
        <FormField id="give-role-team" label="In team">
          <Select value={teamId} onValueChange={(v) => (setTeamId(v), setError(''))}>
            <SelectTrigger id="give-role-team" data-testid="give-role-team">
              <SelectValue placeholder="Choose a team" />
            </SelectTrigger>
            <SelectContent>
              {teams.map((t) => (
                <SelectItem key={t.teamId} value={t.teamId}>
                  {t.teamName}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </div>
    </DialogShell>
  );
}
