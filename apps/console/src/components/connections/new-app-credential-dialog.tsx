'use client';

import * as React from 'react';
import { useForm } from 'react-hook-form';
import { Activity, Search } from 'lucide-react';
import { toast } from 'sonner';

import { useSignInWindow } from '@/components/connections/sign-in';
import { CopyButton } from '@/components/shared/copy-button';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { FormTextField } from '@/components/shared/form-text-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { ListEmpty } from '@/components/shared/query-states';
import { Row, Rows } from '@/components/shared/surface';
import { Stepper } from '@/components/shared/stepper';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { useCreateAppCredential, useStartCredentialCheck } from '@/hooks/connections-queries';
import { type SystemCard, useConnectionKinds, useSystems } from '@/hooks/systems-queries';
import { pluginGroups, type KindField, type Kinds } from '@/lib/connect-plan';
import { fieldErrors, schemaForFields } from '@/lib/field-schema';
import type { AppCredentialRow } from '@/lib/types/connections';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

/** The apps a team may bring its own OAuth client for: the plugins that sign in with an account. */
function signsIn(card: SystemCard, kinds: Kinds | undefined) {
  const kind = kinds?.kinds.find((k) => k.id === (card.authKind ?? card.plugin?.kinds[0]));
  return card.kind === 'plugin' && Boolean(card.plugin) && Boolean(kind?.signsIn);
}

/**
 * New app credential: an admin picks an app, gives the team's own OAuth client (client ID, secret, the access to ask
 * for) and creates it, or creates it and tests it by signing in with their own account. The app's accounts then sign
 * in through that client. The secret is sealed by the service and never shown again.
 */
export function NewAppCredentialDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const systems = useSystems();
  const kinds = useConnectionKinds();
  const all = kinds.data as Kinds | undefined;
  const [q, setQ] = React.useState('');
  const [app, setApp] = React.useState<SystemCard | null>(null);
  const apps = (systems.data ?? []).filter((c) => signsIn(c, all) && (!q || c.name.toLowerCase().includes(q.toLowerCase())));
  const close = () => {
    setApp(null);
    setQ('');
    onOpenChange(false);
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !o && close()}
      size="md"
      title={app ? `${app.name} app credential` : 'New app credential'}
      description={app ? `Register an app with ${app.name}, then give its client ID and secret.` : 'Pick the app your OAuth client is for.'}
      headerExtra={<Stepper steps={['App', 'Your own app']} current={app ? 2 : 1} className="pt-3" testId="new-credential-steps" />}
      data-testid="new-credential"
      footer={
        app ? undefined : (
          <Button variant="outline" onClick={close}>
            Cancel
          </Button>
        )
      }
    >
      {app && all ? (
        <OwnClientForm card={app} kinds={all} onBack={() => setApp(null)} onDone={close} />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search apps" aria-label="Search apps" className="pl-9" data-testid="new-credential-search" />
          </div>
          {systems.isPending || kinds.isPending ? (
            <Skeleton className="h-32 w-full" />
          ) : !apps.length ? (
            <ListEmpty icon={Search} noun="apps" filtered={Boolean(q)} onClear={() => setQ('')} description="No app that signs in with an account is turned on for this install." />
          ) : (
            <Rows className="rounded-md border">
              {apps.map((c) => {
                // An app that already signs in with the team's own client is edited in the list, not added again.
                const has = c.credential?.type === 'own';
                return (
                  <Row
                    key={c.id}
                    leading={
                      <Avatar className="size-8 rounded-md">
                        {c.logo && <AvatarImage src={c.logo} alt="" />}
                        <AvatarFallback className="rounded-md text-xs font-semibold">{initials(c.name)}</AvatarFallback>
                      </Avatar>
                    }
                    title={c.name}
                    description={has ? 'Already signs in with your own app; edit it in the list' : (c.kindLabel ?? 'Sign in with an account')}
                    trailing={
                      <Button size="sm" variant="ghost" disabled={has} onClick={() => setApp(c)} data-testid={`new-credential-choose-${c.id}`}>
                        Choose
                      </Button>
                    }
                  />
                );
              })}
            </Rows>
          )}
        </div>
      )}
    </DialogShell>
  );
}

function OwnClientForm({ card, kinds, onBack, onDone }: { card: SystemCard; kinds: Kinds; onBack: () => void; onDone: () => void }) {
  const plugin = card.plugin!;
  const kind = kinds.kinds.find((k) => k.id === (card.authKind ?? plugin.kinds[0]))!;
  // The client's fields as the API describes them for this app's sign-in kind.
  const fields: KindField[] = pluginGroups(kind, kinds, plugin, 'own').main.filter((f) => f.name === 'clientId' || f.name === 'clientSecret');
  const schema = schemaForFields(fields);
  const form = useForm<Record<string, string>>({ defaultValues: { clientId: '', clientSecret: '' } });
  const [scopes, setScopes] = React.useState<string[]>(plugin.scopes);
  const [error, setError] = React.useState<string | null>(null);
  const [testing, setTesting] = React.useState(false);
  const create = useCreateAppCredential();
  const startCheck = useStartCredentialCheck();
  // The credential this window made, so a second press tests it again instead of adding another.
  const made = React.useRef<AppCredentialRow | null>(null);

  const signIn = useSignInWindow({
    onConnected: (m) => {
      setTesting(false);
      toast.success(`The ${card.name} app credential works`, { description: m.account ? `Signed in as ${m.account}.` : undefined });
      onDone();
    },
    onFailed: (why) => {
      setTesting(false);
      setError(`Created, but the test with your account did not pass: ${why}`);
    },
  });

  /** Checks the fields in place; false when one needs fixing. Synchronous, so a sign-in window may open after it. */
  const valid = () => {
    const errors = fieldErrors(schema.safeParse(form.getValues()));
    form.clearErrors();
    for (const [name, msg] of Object.entries(errors)) form.setError(name, { type: 'schema', message: msg });
    if (!scopes.length) {
      setError(`Pick at least one permission for ${card.name} to ask for.`);
      return false;
    }
    return Object.keys(errors).length === 0;
  };
  const save = async () => {
    if (made.current) return made.current;
    const v = form.getValues();
    made.current = await create.mutateAsync({ app: card.id, clientId: v.clientId.trim(), clientSecret: v.clientSecret, scopes });
    return made.current;
  };

  const createOnly = async () => {
    setError(null);
    if (!valid()) return;
    try {
      await save();
      toast.success(`Saved your own ${card.name} app`, { description: 'Test it with your account from the list.' });
      onDone();
    } catch (e) {
      setError(message(e));
    }
  };
  const createAndTest = async () => {
    setError(null);
    if (!valid()) return;
    // Opened in the click, before any call: a window opened after an await is blocked as a pop-up.
    const w = signIn.open(card.name, card.logo);
    if (!w) return;
    setTesting(true);
    try {
      const row = await save();
      const account = { appId: row.app, accountId: row.id };
      const s = await startCheck.mutateAsync(account);
      w.go(s, account, { check: true });
    } catch (e) {
      w.fail(message(e));
      setTesting(false);
      setError(message(e));
    }
  };

  return (
    <Form {...form}>
      <div className="flex flex-col gap-4" data-testid="new-credential-form">
        <div className="grid gap-3 sm:grid-cols-2">
          <FormTextField control={form.control} name="clientId" label="Client ID" testId="new-credential-client-id" />
          <FormTextField control={form.control} name="clientSecret" label="Client secret" type="password" hint="Sealed when saved; never shown again." testId="new-credential-client-secret" />
        </div>
        {kinds.redirectUri && (
          <FormField id="new-credential-return" label="Return address" hint={`Register it on your ${card.name} app.`}>
            <div className="flex min-w-0 items-center gap-1">
              <Input id="new-credential-return" readOnly value={kinds.redirectUri} className="font-mono text-xs" />
              <CopyButton text={kinds.redirectUri} />
            </div>
          </FormField>
        )}
        {plugin.scopes.length > 0 && (
          <fieldset className="flex flex-col gap-2" data-testid="new-credential-scopes">
            <legend className="mb-1 text-sm font-medium">Permissions it asks for</legend>
            {plugin.scopes.map((s) => (
              <label key={s} className="flex items-center gap-2 text-sm">
                <Checkbox checked={scopes.includes(s)} onCheckedChange={(on) => setScopes((cur) => (on ? [...cur, s] : cur.filter((x) => x !== s)))} />
                {s}
              </label>
            ))}
          </fieldset>
        )}
        {error && (
          <p className="text-sm text-destructive" role="alert" data-testid="new-credential-error">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
          <Button variant="outline" onClick={onBack} disabled={testing || create.isPending} data-testid="new-credential-back">
            Back
          </Button>
          <LoadingButton variant="outline" isLoading={testing} onClick={() => void createAndTest()} data-testid="new-credential-test">
            <Activity />
            Test with my account
          </LoadingButton>
          <LoadingButton isLoading={create.isPending && !testing} disabled={testing} onClick={() => void createOnly()} data-testid="new-credential-create">
            Create
          </LoadingButton>
        </div>
      </div>
    </Form>
  );
}
