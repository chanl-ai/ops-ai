'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { AccessOptions, Capability, RoleInput } from '@/lib/types/governance';

import { CAPABILITY_LABEL } from './access-meta';

const HELP: Record<Capability, string> = {
  author: 'Edit agents and workflow drafts',
  approve: 'Decide reviews and publish requests',
  publish: 'Request a publish to production',
};

/** Lets a person or group author, approve or publish in a team. */
export function RoleDialog({
  open,
  onOpenChange,
  options,
  currentTeamId,
  canPickTeam,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  options?: AccessOptions;
  currentTeamId: string;
  canPickTeam: boolean;
  onSubmit: (input: RoleInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [kind, setKind] = React.useState<'person' | 'group'>('group');
  const [principal, setPrincipal] = React.useState('');
  const [teamId, setTeamId] = React.useState(currentTeamId);
  const [caps, setCaps] = React.useState<Capability[]>(['approve']);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setKind('group');
    setPrincipal('');
    setTeamId(currentTeamId);
    setCaps(['approve']);
    setError(null);
  }, [open, currentTeamId]);

  const list = kind === 'group' ? (options?.groups ?? []) : (options?.people ?? []);

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Add who can author, approve or publish"
      description="Publishing still needs approval from a different person in Reviews."
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <p className="text-xs text-destructive">{error ?? ''}</p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={isPending}
              onClick={async () => {
                if (!principal) return setError(`Choose a ${kind}.`);
                if (!caps.length) return setError('Choose at least one capability.');
                try {
                  await onSubmit({ principal, principalKind: kind, teamId, capabilities: caps });
                  onOpenChange(false);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Add
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <RadioGroup value={kind} onValueChange={(v) => (setKind(v as 'person' | 'group'), setPrincipal(''), setError(null))} className="flex gap-4">
          {(['group', 'person'] as const).map((k) => (
            <div key={k} className="flex items-center gap-2">
              <RadioGroupItem value={k} id={`role-kind-${k}`} />
              <Label htmlFor={`role-kind-${k}`} className="font-normal">
                {k === 'group' ? 'Group' : 'Person'}
              </Label>
            </div>
          ))}
        </RadioGroup>

        <FormField id="role-principal" label={kind === 'group' ? 'Group' : 'Person'} hint={kind === 'group' ? 'Groups sync from Entra ID.' : undefined}>
          <Select value={principal} onValueChange={(v) => (setPrincipal(v), setError(null))}>
            <SelectTrigger id="role-principal" className="w-full">
              <SelectValue placeholder={kind === 'group' ? 'Choose a group' : 'Choose a person'} />
            </SelectTrigger>
            <SelectContent>
              {list.map((x) => (
                <SelectItem key={x} value={x}>
                  {x}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>

        {canPickTeam && (
          <FormField id="role-team" label="Team">
            <Select value={teamId} onValueChange={setTeamId}>
              <SelectTrigger id="role-team" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {options?.teams.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}

        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1.5 text-sm font-medium">Can</legend>
          {(['author', 'approve', 'publish'] as const).map((c) => (
            <div key={c} className="flex items-start gap-2">
              <Checkbox id={`role-cap-${c}`} checked={caps.includes(c)} onCheckedChange={(v) => (setCaps((cur) => (v ? [...cur, c] : cur.filter((x) => x !== c))), setError(null))} className="mt-0.5" />
              <Label htmlFor={`role-cap-${c}`} className="flex flex-col items-start gap-0.5 font-normal">
                <span className="text-sm font-medium">{CAPABILITY_LABEL[c]}</span>
                <span className="text-xs text-muted-foreground">{HELP[c]}</span>
              </Label>
            </div>
          ))}
        </fieldset>
      </div>
    </DialogShell>
  );
}
