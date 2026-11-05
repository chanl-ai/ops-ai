'use client';

import * as React from 'react';

import { CallbackUrl } from '@/components/connections/callback-url';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { Search } from 'lucide-react';
import { toast } from 'sonner';

import { credentialHref } from '@/components/connections/credential-display';
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
 * ask for, the settings its registration keeps), with no account needed. It then opens on its own page, where
 * accounts connect with it and Test with my account runs. `app` starts it on one app (an app's page, the Connect
 * window); `onCreated` keeps the person where they are, handed the new credential, instead of opening its page.
 * The secret is sealed and never shown again.
 */
export function NewAppCredentialDialog({
  open,
  onOpenChange,
  app: fixed,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  app?: string;
  onCreated?: (credentialId: string) => void;
}) {
  const systems = useSystems();
  const kinds = useConnectionKinds();
  const all = kinds.data as Kinds | undefined;
  const [q, setQ] = React.useState('');
  const [picked, setApp] = React.useState<SystemCard | null>(null);
  const app = picked ?? (systems.data ?? []).find((c) => c.id === fixed) ?? null;
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
      title={app ? `${app.name} auth config` : 'New auth config'}
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
        <OwnClientForm card={app} kinds={all} onBack={fixed ? undefined : () => setApp(null)} onDone={close} onCreated={onCreated} />
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

function OwnClientForm({
  card,
  kinds,
  onBack,
  onDone,
  onCreated,
}: {
  card: SystemCard;
  kinds: Kinds;
  onBack?: () => void;
  onDone: () => void;
  onCreated?: (credentialId: string) => void;
}) {
  const plugin = card.plugin!;
  const router = useRouter();
  // The settings the app's registration keeps (a tenant), held by the credential rather than each account.
  const registration = plugin.settings.filter((x) => x.credential);
  const schema = schemaForFields(CLIENT);
  const form = useForm<Record<string, string>>({ defaultValues: { name: '', clientId: '', clientSecret: '', ...Object.fromEntries(registration.map((x) => [`setting__${x.name}`, x.default ?? ''])) } });
  const [scopes, setScopes] = React.useState<string[]>(plugin.scopes.map((s) => s.id));
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
      const settings = Object.fromEntries(registration.map((x) => [x.name, (v[`setting__${x.name}`] ?? '').trim()]).filter(([, val]) => val));
      const made = await create.mutateAsync({
        app: card.id,
        ...(v.name.trim() ? { name: v.name.trim() } : {}),
        clientId: v.clientId.trim(),
        ...(v.clientSecret ? { clientSecret: v.clientSecret } : {}),
        scopes,
        ...(Object.keys(settings).length ? { settings } : {}),
      });
      toast.success(`Saved your own ${card.name} app`, { description: onCreated ? undefined : 'Connect an account with it, or test it with yours.' });
      onDone();
      if (onCreated) onCreated(made.id);
      else router.push(credentialHref(made));
    } catch (e) {
      setError(message(e));
    }
  };

  return (
    <Form {...form}>
      <div className="flex flex-col gap-4" data-testid="new-credential-form">
        <FormTextField control={form.control} name="name" label="Name" optional placeholder={`e.g. ${card.name} credentials`} testId="new-credential-name" />
        <div className="grid gap-3">
          <FormTextField control={form.control} name="clientId" label="Client ID" testId="new-credential-client-id" />
          <FormTextField control={form.control} name="clientSecret" label="Client secret" type="password" optional testId="new-credential-client-secret" />
        </div>
        <CallbackUrl app={card.name} id="new-credential-return" testId="new-credential-callback" />
        {plugin.scopes.length > 0 && (
          <fieldset className="flex flex-col gap-2" data-testid="new-credential-scopes">
            <legend className="mb-1 text-sm font-medium">Permissions it asks for</legend>
            {plugin.scopes.map((s) => (
              <label key={s.id} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={s.required || scopes.includes(s.id)}
                  disabled={s.required}
                  onCheckedChange={(on) => setScopes((cur) => (on ? [...cur, s.id] : cur.filter((x) => x !== s.id)))}
                  data-testid={`new-credential-scope-${s.id}`}
                />
                {s.label}
                {s.required && <span className="text-xs text-muted-foreground">Always asked for</span>}
              </label>
            ))}
          </fieldset>
        )}
        {registration.map((x) => (
          <FormTextField key={x.name} control={form.control} name={`setting__${x.name}`} label={x.label} optional={Boolean(x.default)} testId={`new-credential-setting-${x.name}`} />
        ))}
        {error && (
          <p className="text-sm text-destructive" role="alert" data-testid="new-credential-error">
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-2 border-t pt-4">
          {onBack ? (
            <Button variant="outline" onClick={onBack} disabled={create.isPending} data-testid="new-credential-back">
              Back
            </Button>
          ) : (
            <Button variant="outline" onClick={onDone} disabled={create.isPending} data-testid="new-credential-cancel">
              Cancel
            </Button>
          )}
          <LoadingButton isLoading={create.isPending} onClick={() => void createOne()} data-testid="new-credential-create">
            Create
          </LoadingButton>
        </div>
      </div>
    </Form>
  );
}
