'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { Search } from 'lucide-react';
import { toast } from 'sonner';

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
import { type SystemCard, useConnectionKinds, useCreateAppCredential, useSystems } from '@/hooks/systems-queries';
import type { KindField, Kinds } from '@/lib/connect-plan';
import { fieldErrors, schemaForFields } from '@/lib/field-schema';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));
const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

/** The apps a team may bring its own OAuth client for: the plugins that sign in with an account or fetch a token. */
function signsIn(card: SystemCard, kinds: Kinds | undefined) {
  const kind = kinds?.kinds.find((k) => k.id === (card.authKind ?? card.plugin?.kinds[0]));
  return card.kind === 'plugin' && Boolean(card.plugin) && Boolean(kind?.signsIn || kind?.holdsToken);
}

// The OAuth client's two fields: typed here only, the one place a team's client is entered.
const CLIENT: KindField[] = [
  { name: 'clientId', label: 'Client ID', secret: false, required: true, advanced: false },
  // None for an app that proves itself with a signed assertion; each account then holds its signing pair.
  { name: 'clientSecret', label: 'Client secret', secret: true, required: false, advanced: false },
];

/**
 * New app credential: an admin picks an app and gives the team's own OAuth client (client ID, secret, the access to
 * ask for), with no account needed. It then opens on its own page, where accounts connect with it and Test with my
 * account runs; the Connect window and the app's Settings pick it. The secret is sealed and never shown again.
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
              {apps.map((c) => (
                <Row
                  key={c.id}
                  leading={
                    <Avatar className="size-8 rounded-md">
                      {c.logo && <AvatarImage src={c.logo} alt="" />}
                      <AvatarFallback className="rounded-md text-xs font-semibold">{initials(c.name)}</AvatarFallback>
                    </Avatar>
                  }
                  title={c.name}
                  description={c.kindLabel ?? 'Sign in with an account'}
                  trailing={
                    <Button size="sm" variant="ghost" onClick={() => setApp(c)} data-testid={`new-credential-choose-${c.id}`}>
                      Choose
                    </Button>
                  }
                />
              ))}
            </Rows>
          )}
        </div>
      )}
    </DialogShell>
  );
}

function OwnClientForm({ card, kinds, onBack, onDone }: { card: SystemCard; kinds: Kinds; onBack: () => void; onDone: () => void }) {
  const plugin = card.plugin!;
  const router = useRouter();
  const schema = schemaForFields(CLIENT);
  const form = useForm<Record<string, string>>({ defaultValues: { name: '', clientId: '', clientSecret: '' } });
  const [scopes, setScopes] = React.useState<string[]>(plugin.scopes);
  const [error, setError] = React.useState<string | null>(null);
  const create = useCreateAppCredential();

  const createOne = async () => {
    setError(null);
    const errors = fieldErrors(schema.safeParse(form.getValues()));
    form.clearErrors();
    for (const [name, msg] of Object.entries(errors)) form.setError(name, { type: 'schema', message: msg });
    if (!scopes.length) setError(`Pick at least one permission for ${card.name} to ask for.`);
    if (Object.keys(errors).length || !scopes.length) return;
    const v = form.getValues();
    try {
      const made = await create.mutateAsync({ app: card.id, ...(v.name.trim() ? { name: v.name.trim() } : {}), clientId: v.clientId.trim(), ...(v.clientSecret ? { clientSecret: v.clientSecret } : {}), scopes });
      toast.success(`Saved your own ${card.name} app`, { description: 'Connect an account with it, or test it with yours.' });
      onDone();
      router.push(`/integrations/credentials/${encodeURIComponent(made.id)}`);
    } catch (e) {
      setError(message(e));
    }
  };

  return (
    <Form {...form}>
      <div className="flex flex-col gap-4" data-testid="new-credential-form">
        <FormTextField control={form.control} name="name" label="Name" optional placeholder={`e.g. ${card.name} credentials`} testId="new-credential-name" />
        <div className="grid gap-3 sm:grid-cols-2">
          <FormTextField control={form.control} name="clientId" label="Client ID" testId="new-credential-client-id" />
          <FormTextField control={form.control} name="clientSecret" label="Client secret" type="password" optional hint="Sealed when saved; never shown again. Blank for an app that signs an assertion." testId="new-credential-client-secret" />
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
          <Button variant="outline" onClick={onBack} disabled={create.isPending} data-testid="new-credential-back">
            Back
          </Button>
          <LoadingButton isLoading={create.isPending} onClick={() => void createOne()} data-testid="new-credential-create">
            Create
          </LoadingButton>
        </div>
      </div>
    </Form>
  );
}
