'use client';

import Link from 'next/link';

import { FormField } from '@/components/shared/form-field';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useAppCredentials } from '@/hooks/systems-queries';

// Ops AI's app has no credential of the team's; a Select item needs a value, so it stands for `null`.
const OPS_AI = 'ops-ai';

/**
 * Which OAuth client an app's account signs in with: Ops AI's app, or one of the team's app credentials for that app
 * (GET /v1/app-credentials?app=). A client is typed only in New app credential under Credentials, which the link opens.
 * `platform` is whether the install has Ops AI's app for this app; without it only the team's own are offered.
 */
export function AppCredentialPicker({
  app,
  value,
  onChange,
  platform,
  disabled = false,
  id = 'app-credential',
  testId = 'app-credential-picker',
}: {
  app: string;
  value: string | null;
  onChange: (credential: string | null) => void;
  platform: boolean;
  disabled?: boolean;
  id?: string;
  testId?: string;
}) {
  const creds = useAppCredentials(app);
  const own = (creds.data ?? []).filter((c) => c.type === 'own');
  const none = !platform && !own.length;
  const add = (
    <Link href="/integrations/credentials" className="underline underline-offset-4" data-testid={`${testId}-add`}>
      Add one under Credentials
    </Link>
  );
  const hint = creds.isError ? 'Couldn’t load the team’s app credentials.' : none ? <>This install has no app of its own for it. {add}</> : add;
  return (
    <FormField id={id} label="App credential" hint={hint}>
      {creds.isPending ? (
        <Skeleton className="h-9 w-full" />
      ) : (
        <Select value={value ?? (platform ? OPS_AI : '')} onValueChange={(v) => onChange(v === OPS_AI ? null : v)} disabled={disabled || none}>
          <SelectTrigger id={id} className="w-full" data-testid={testId}>
            <SelectValue placeholder="Pick an app credential" />
          </SelectTrigger>
          <SelectContent>
            {platform && <SelectItem value={OPS_AI}>Ops AI’s app</SelectItem>}
            {own.map((c) => (
              <SelectItem key={c.id} value={c.id} data-testid={`${testId}-option-${c.id}`}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </FormField>
  );
}
