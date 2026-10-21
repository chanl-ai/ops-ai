'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { TeamSelectField } from '@/components/shared/team-select-field';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import type { InviteInput, MemberRole, SettingsLookups } from '@/lib/types/settings';

/**
 * Invites people by email with one role: to the current team, or to a picked team when `teams` is given. No email goes
 * out; the host shows each person's link once (`InviteLinksDialog`) after `onSubmit` resolves. Reusable by any page that
 * adds people to a team: the Access page owns it (roles-and-permissions, "Reusable parts").
 */
export function InviteDialog({
  open,
  onOpenChange,
  teamName,
  roles,
  onSubmit,
  isPending,
  teams,
  defaultTeamId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  teamName: string;
  roles: SettingsLookups['roles'];
  onSubmit: (input: InviteInput) => Promise<unknown>;
  isPending: boolean;
  /** Shows a team field. Leave it out when the service invites to the team the request is made for. */
  teams?: { id: string; name: string }[];
  defaultTeamId?: string;
}) {
  const [teamId, setTeamId] = React.useState(defaultTeamId ?? '');
  const [emails, setEmails] = React.useState('');
  // The least the invitee can do, so an unchanged choice never hands out approval rights.
  const [role, setRole] = React.useState<MemberRole>('viewer');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setTeamId(defaultTeamId ?? '');
    setEmails('');
    setRole('viewer');
    setError(null);
  }, [open, defaultTeamId]);

  const list = emails
    .split(/[\s,;]+/)
    .map((e) => e.trim())
    .filter(Boolean);

  const submit = async () => {
    if (!list.length) return setError('Enter at least one email address.');
    try {
      await onSubmit({ emails: list, role, ...(teams ? { teamId } : {}) });
      onOpenChange(false);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={teams ? `Invite to ${teams.find((t) => t.id === teamId)?.name ?? 'a team'}` : `Invite to ${teamName}`}
      description="No email is sent. You get a link for each person to pass on yourself; it is shown once and works for 7 days."
      onSubmit={submit}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton type="submit" isLoading={isPending}>
            {list.length > 1 ? `Invite ${list.length} people` : 'Invite'}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {teams && <TeamSelectField id="invite-team" teams={teams} value={teamId} onChange={setTeamId} hint="Their role applies within this team." />}
        <FormField id="invite-emails" label="Email addresses" hint="Separate several with commas or new lines. Only the domains allowed in Settings → Sign-in." error={error ?? undefined}>
          <Textarea id="invite-emails" rows={3} value={emails} onChange={(e) => (setEmails(e.target.value), setError(null))} placeholder="e.g. first.last@harborpine.example" aria-invalid={!!error} />
        </FormField>
        <div className="flex flex-col gap-2">
          <Label>Role</Label>
          <RadioGroup value={role} onValueChange={(v) => setRole(v as MemberRole)} className="gap-3">
            {roles.map((r) => (
              <div key={r.value} className="flex items-start gap-2">
                <RadioGroupItem value={r.value} id={`invite-role-${r.value}`} className="mt-0.5" />
                <Label htmlFor={`invite-role-${r.value}`} className="flex flex-col items-start gap-0.5 font-normal">
                  <span className="text-sm font-medium">{r.label}</span>
                  <span className="text-xs text-muted-foreground">{r.description}</span>
                </Label>
              </div>
            ))}
          </RadioGroup>
        </div>
      </div>
    </DialogShell>
  );
}
