'use client';

import * as React from 'react';

import { NewAppCredentialDialog } from '@/components/connections/new-app-credential-dialog';
import { FormField } from '@/components/shared/form-field';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { AddAuthConfigButton } from '@/components/connections/app-actions';
import { type SystemCard, useAppCredentials } from '@/hooks/systems-queries';
import { addAuthConfigFirst } from '@/lib/app-state';

// Ops AI's app has no credential of the team's; a Select item needs a value, so it stands for `null`.
const OPS_AI = 'ops-ai';

/**
 * Which OAuth client an app's account signs in with: Ops AI's app, or one of the team's app credentials for that app
 * (GET /v1/app-credentials?app=), each with its secret's last four characters. Add your own app opens New app
 * credential in place, on this app, and picks what it makes.
 * `platform` is whether the install has Ops AI's app for this app; without it only the team's own are offered. An
 * app whose card reads needs_auth_config has nothing to pick: the picker says what to add and opens it.
 */
export function AppCredentialPicker({
  card,
  value,
  onChange,
  platform,
  disabled = false,
  id = 'app-credential',
  testId = 'app-credential-picker',
}: {
  card: Pick<SystemCard, 'id' | 'name' | 'appState'>;
  value: string | null;
  onChange: (credential: string | null) => void;
  platform: boolean;
  disabled?: boolean;
  id?: string;
  testId?: string;
}) {
  const creds = useAppCredentials(card.id);
  const own = (creds.data ?? []).filter((c) => c.type === 'own');
  const [adding, setAdding] = React.useState(false);
  // With no app of Ops AI's, the team's one auth config is the only choice, so it starts picked.
  const only = !platform && own.length === 1 ? own[0].id : null;
  React.useEffect(() => {
    if (value === null && only) onChange(only);
  }, [value, only]);
  if (card.appState === 'needs_auth_config')
    return (
      <FormField id={id} label="Auth config">
        <p className="text-sm" data-testid={`${testId}-missing`}>
          {addAuthConfigFirst(card.name)}{' '}
          <AddAuthConfigButton appId={card.id} link onCreated={onChange} testId={`${testId}-add`} />
        </p>
      </FormField>
    );
  const add = (
    <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => setAdding(true)} disabled={disabled} data-testid={`${testId}-add`}>
      Add your own app
    </Button>
  );
  const hint = creds.isError ? 'Couldn’t load the team’s auth configs.' : add;
  return (
    <FormField id={id} label="Auth config" hint={hint}>
      {creds.isPending ? (
        <Skeleton className="h-9 w-full" />
      ) : (
        <Select value={value ?? (platform ? OPS_AI : '')} onValueChange={(v) => onChange(v === OPS_AI ? null : v)} disabled={disabled}>
          <SelectTrigger id={id} className="w-full" data-testid={testId}>
            <SelectValue placeholder="Pick an auth config" />
          </SelectTrigger>
          <SelectContent>
            {platform && <SelectItem value={OPS_AI}>Ops AI’s app</SelectItem>}
            {own.map((c) => (
              <SelectItem key={c.id} value={c.id} data-testid={`${testId}-option-${c.id}`}>
                {c.secretEnds ? `${c.name} · secret ends in ${c.secretEnds}` : c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      <NewAppCredentialDialog open={adding} onOpenChange={setAdding} app={card.id} onCreated={(id) => (setAdding(false), onChange(id))} />
    </FormField>
  );
}
