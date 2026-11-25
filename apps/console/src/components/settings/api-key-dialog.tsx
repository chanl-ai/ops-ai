'use client';

import * as React from 'react';
import { AlertTriangle } from 'lucide-react';

import { CopyButton } from '@/components/shared/copy-button';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { type PickedTeam, TeamSelectField } from '@/components/shared/team-select-field';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ApiKeyInput, ApiScope } from '@/lib/types/settings';
import { nameError } from '@/lib/validation/names';

const EXPIRY = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
  { value: 'never', label: 'Never' },
];

/** Creates an API key, then shows the full key once. Closing the dialog is the only way past the key. */
export function ApiKeyDialog({
  open,
  onOpenChange,
  scopes,
  onSubmit,
  isPending,
  pickTeam,
  defaultTeam,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  scopes: ApiScope[];
  onSubmit: (input: ApiKeyInput) => Promise<{ key: string }>;
  isPending: boolean;
  /** Platform scope only: shows a team field offering the teams the person may create keys in (`allowed`). */
  pickTeam?: { allowed?: string[] };
  defaultTeam?: PickedTeam;
}) {
  const [team, setTeam] = React.useState<PickedTeam | null>(defaultTeam ?? null);
  const [name, setName] = React.useState('');
  const [picked, setPicked] = React.useState<string[]>(['read', 'write']);
  const [expiry, setExpiry] = React.useState('365');
  const [error, setError] = React.useState<string | null>(null);
  const [key, setKey] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!open) return;
    setTeam(defaultTeam ?? null);
    setName('');
    setPicked(['read', 'write']);
    setExpiry('365');
    setError(null);
    setKey(null);
  }, [open, defaultTeam?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (key)
    return (
      <DialogShell
        open={open}
        onOpenChange={onOpenChange}
        size="md"
        title="Copy your API key"
        description={`${name} is ready.`}
        footer={
          <div className="flex w-full justify-end">
            <Button onClick={() => onOpenChange(false)}>I’ve stored the key</Button>
          </div>
        }
      >
        <div className="flex flex-col gap-3">
          <Alert>
            <AlertTriangle />
            <AlertDescription>This is the only time the full key is shown. Store it in the calling system’s secret store now.</AlertDescription>
          </Alert>
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2">
            <code className="min-w-0 flex-1 font-mono text-xs break-all">{key}</code>
            <CopyButton text={key} />
          </div>
        </div>
      </DialogShell>
    );

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Create API key"
      description="For a system that starts runs or reads logs for this team. Calls made with it are logged under its name."
      footer={
        <div className="flex w-full items-center justify-between gap-2">
          <p className="text-xs text-destructive-text">{error ?? ''}</p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={isPending}
              onClick={async () => {
                const nameIssue = nameError(name, 'Name the key.');
                if (nameIssue) return setError(nameIssue);
                if (!picked.length) return setError('Pick at least one scope.');
                try {
                  const res = await onSubmit({ name, scopes: picked, expiresInDays: expiry === 'never' ? null : Number(expiry), ...(pickTeam ? { teamId: team?.id ?? '' } : {}) });
                  setKey(res.key);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Create key
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {pickTeam && <TeamSelectField id="key-team" value={team} onChange={setTeam} allowed={pickTeam.allowed} reason="You can’t create keys in this team." hint="Runs started with the key belong to this team." />}
        <FormField id="key-name" label="Name" hint="Name the system that will use it.">
          <Input id="key-name" value={name} onChange={(e) => (setName(e.target.value), setError(null))} placeholder="e.g. Core banking event bridge" />
        </FormField>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1.5 text-sm font-medium">Scopes</legend>
          {scopes.map((s) => (
            <div key={s.value} className="flex items-center gap-2">
              <Checkbox id={`key-scope-${s.value}`} checked={picked.includes(s.value)} onCheckedChange={(v) => (setPicked((p) => (v ? [...p, s.value] : p.filter((x) => x !== s.value))), setError(null))} />
              <Label htmlFor={`key-scope-${s.value}`} className="font-normal">
                {s.label} <code className="font-mono text-xs text-muted-foreground">{s.value}</code>
              </Label>
            </div>
          ))}
        </fieldset>
        <FormField id="key-expiry" label="Expires">
          <Select value={expiry} onValueChange={setExpiry}>
            <SelectTrigger id="key-expiry" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {EXPIRY.map((e) => (
                <SelectItem key={e.value} value={e.value}>
                  {e.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </div>
    </DialogShell>
  );
}
