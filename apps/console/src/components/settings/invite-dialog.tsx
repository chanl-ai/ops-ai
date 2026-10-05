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

/** Invites people by email with one role: to the current team, or to a picked team in Platform scope. */
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
  /** Platform scope only: shows a team field. */
  teams?: { id: string; name: string }[];
  defaultTeamId?: string;
}) {
  const [teamId, setTeamId] = React.useState(defaultTeamId ?? '');
  const [emails, setEmails] = React.useState('');
  const [role, setRole] = React.useState<MemberRole>('approver');
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setTeamId(defaultTeamId ?? '');
    setEmails('');
    setRole('approver');
    setError(null);
  }, [open, defaultTeamId]);

  const list = emails
    .split(/[\s,;]+/)
    .map((e) => e.trim())
    .filter(Boolean);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={teams ? `Invite to ${teams.find((t) => t.id === teamId)?.name ?? 'a team'}` : `Invite to ${teamName}`}
      description="They sign in with single sign-on. The invite expires in 7 days."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            onClick={async () => {
              if (!list.length) return setError('Enter at least one email address.');
              try {
                await onSubmit({ emails: list, role, ...(teams ? { teamId } : {}) });
                onOpenChange(false);
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            {list.length > 1 ? `Invite ${list.length} people` : 'Invite'}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {teams && <TeamSelectField id="invite-team" teams={teams} value={teamId} onChange={setTeamId} hint="Their role applies within this team." />}
        <FormField id="invite-emails" label="Email addresses" hint="Separate several with commas or new lines. Bank addresses only." error={error ?? undefined}>
          <Textarea id="invite-emails" rows={3} value={emails} onChange={(e) => (setEmails(e.target.value), setError(null))} placeholder="e.g. first.last@northfieldbank.com" aria-invalid={!!error} />
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
