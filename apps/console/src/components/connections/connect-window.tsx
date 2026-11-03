'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';

import { appHref } from '@/components/connections/systems-grid';
import { useSignInWindow } from '@/components/connections/sign-in';
import { CopyButton } from '@/components/shared/copy-button';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { FormTextField } from '@/components/shared/form-text-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Form } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useTeam } from '@/hooks/use-team';
import {
  type SystemCard,
  type TeamPluginBody,
  useAddAccount,
  useDeleteConnection,
  useSetTeamPlugin,
  useStartSignIn,
  useTestEnvironment,
} from '@/hooks/systems-queries';
import { draftFor, keyed, pluginGroups, turnOnBody, type KindField, type Kinds } from '@/lib/connect-plan';
import { fieldErrors, schemaForFields } from '@/lib/field-schema';

type App = 'platform' | 'own';

/** A plugin the Connect window connects: one that signs in with an account, through Ops AI's app or the team's own. */
export function connectsInWindow(card: SystemCard, kinds: Kinds | undefined): boolean {
  const kind = kinds?.kinds.find((k) => k.id === (card.authKind ?? card.plugin?.kinds[0]));
  return card.kind === 'plugin' && Boolean(kind?.signsIn);
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * The one Connect window for an app that signs in with an account: which app credential (Ops AI's app or
 * the team's own client, reused when the app already has one), the access it asks for, then Authorize. The sign-in
 * window opens on the click and closes once access is allowed; the account's first test then runs in the background.
 * `another` adds a second named account of an app the team has connected. Cancel removes what the window made.
 */
export function ConnectWindow({ card, kinds, another = false, open, onOpenChange }: { card: SystemCard; kinds: Kinds; another?: boolean; open: boolean; onOpenChange: (open: boolean) => void }) {
  const router = useRouter();
  const setTeamPlugin = useSetTeamPlugin();
  const addAccount = useAddAccount();
  const start = useStartSignIn();
  const remove = useDeleteConnection();
  const test = useTestEnvironment();
  const { team: current } = useTeam();
  const plugin = card.plugin;
  const kind = kinds.kinds.find((k) => k.id === (card.authKind ?? plugin?.kinds[0]));
  const environment = keyed(kinds).find((e) => e.production)?.id ?? 'production';

  // The app credential the team's connection already signs in with, as the app's card names it.
  const existing = card.connectionId ? card.credential : null;
  const [newClient, setNewClient] = React.useState(false);
  const reusing = Boolean(card.connectionId) && !newClient;
  // Ops AI's own client exists only where the install set it up; without it the team's own is the one way to sign in.
  const managed = card.managedClient ?? Boolean(plugin?.platformApp);
  const [app, setApp] = React.useState<App>(managed ? 'platform' : 'own');
  const chosen: App = reusing ? (existing?.type === 'own' ? 'own' : 'platform') : newClient ? 'own' : app;
  const typing = !reusing && chosen === 'own';
  // The fields this window asks, as the API describes them: the team's own client when it brings one, and the plugin's
  // own settings (Salesforce's sign-in address) when the app is first connected; kept after.
  const asked = reusing ? [] : (plugin?.settings ?? []).filter((x) => !x.locked);
  const fields: KindField[] = [
    ...(plugin && kind ? pluginGroups(kind, kinds, plugin, typing ? 'own' : 'platform').main.filter((f) => f.name === 'clientId' || f.name === 'clientSecret') : []),
    ...asked.map((x) => ({ name: x.name, label: x.label, secret: x.secret, required: !x.default, advanced: Boolean(x.default), default: x.default })),
  ];
  const schema = schemaForFields(fields);
  const form = useForm<Record<string, string>>({
    defaultValues: { clientId: '', clientSecret: '', accountName: '', ...Object.fromEntries((plugin?.settings ?? []).map((x) => [x.name, x.default ?? ''])) },
  });
  // Settings with a default wait under More options, so the default path stays the app credential and Authorize.
  const needed = fields.filter((f) => f.name !== 'clientId' && f.name !== 'clientSecret' && !f.advanced);
  const tuned = fields.filter((f) => f.advanced);

  // Whose account it is and its name sit under More options; a second account opens with them showing.
  const [more, setMore] = React.useState(another);
  const [team, setTeam] = React.useState(true);
  const suggested = another ? `${card.name} · second account` : `${card.name} · ${current?.name ?? 'Team'}`;

  const [waiting, setWaiting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // What this window made, until the sign-in answers: Cancel removes it (and turns a plugin it turned on off again).
  const made = React.useRef<{ id: string | null; turnedOn: boolean } | null>(null);

  const signIn = useSignInWindow({
    onConnected: (m) => {
      made.current = null;
      setWaiting(false);
      toast.success(`${card.name} is connected`, { description: m.account ? `Signed in as ${m.account}.` : undefined });
      onOpenChange(false);
      // Connected once access is allowed; the first test runs after, and a failure shows on the account's row.
      test.mutate({ connectionId: m.connectionId, environment });
      router.push(appHref(card));
    },
    onFailed: (why) => {
      setError(why);
      // A refused sign-in leaves nothing behind, so Authorize again starts from what the window shows now.
      void undo().finally(() => setWaiting(false));
    },
  });

  /** Removes what this window made: the account, and the plugin it turned on. */
  const undo = async () => {
    const m = made.current;
    made.current = null;
    if (!m) return;
    try {
      if (m.id) await remove.mutateAsync(m.id);
      if (m.turnedOn) await setTeamPlugin.mutateAsync({ path: { plugin_id: card.pluginId ?? '' }, body: { enabled: false, environment } as TeamPluginBody });
    } catch (e) {
      toast.error(`Couldn’t remove what was made for ${card.name}`, { description: message(e) });
    }
  };

  if (!plugin || !kind) return null;

  const setting = (f: KindField) => (
    <FormTextField
      key={f.name}
      control={form.control}
      name={f.name}
      label={f.label}
      optional={!f.required}
      type={f.secret ? 'password' : 'text'}
      testId={`connect-window-setting-${f.name}`}
    />
  );

  const authorize = async () => {
    // Checked before the sign-in window opens, and synchronously: a window opened after an await is blocked as a pop-up.
    const values = form.getValues();
    const errors = fieldErrors(schema.safeParse(values));
    form.clearErrors();
    if (Object.keys(errors).length) {
      for (const [name, msg] of Object.entries(errors)) form.setError(name, { type: 'schema', message: msg });
      // A field folded under More options opens it, so its error is seen.
      if (tuned.some((f) => errors[f.name])) setMore(true);
      return;
    }
    const w = signIn.open(card.name, card.logo);
    if (!w) return;
    setError(null);
    setWaiting(true);
    try {
      const draft = draftFor(environment, pluginGroups(kind, kinds, plugin, typing ? 'own' : 'platform'));
      if (typing) {
        draft.settings.clientId = values.clientId.trim();
        draft.secrets.clientSecret = values.clientSecret;
      }
      for (const x of asked.filter((a) => a.perEnvironment)) draft.settings[x.name] = values[x.name] ?? '';
      const teamSettings = Object.fromEntries(asked.filter((a) => !a.perEnvironment).map((a) => [a.name, values[a.name] ?? '']));
      const accountName = (values.accountName ?? '').trim();
      const offered = team ? (plugin.signIn.includes('person_or_team') ? 'person_or_team' : undefined) : plugin.signIn.includes('person') ? 'person' : undefined;
      const body = {
        // A later turn-on that names no client keeps the app credential the team's connection already has.
        ...turnOnBody(kind, plugin, typing ? 'own' : 'platform', draft, teamSettings, !card.connectionId || another, offered),
        ...(another ? { name: accountName || suggested } : { accountName: accountName || suggested }),
      } as TeamPluginBody;
      let id: string;
      if (another) {
        const account = await addAccount.mutateAsync({ path: { plugin_id: card.pluginId ?? '' }, body: body as never });
        id = String(account.id);
        made.current = { id, turnedOn: false };
      } else {
        const view = await setTeamPlugin.mutateAsync({ path: { plugin_id: card.pluginId ?? '' }, body });
        id = String(view.connectionId ?? card.connectionId ?? '');
        made.current = { id: card.connectionId ? null : id, turnedOn: true };
      }
      const s = await start.mutateAsync({ connectionId: id, environment, account: team ? 'team' : 'self' });
      w.go(s, id);
    } catch (e) {
      w.fail(message(e));
      setError(message(e));
      void undo().finally(() => setWaiting(false));
    }
  };

  const cancel = async () => {
    signIn.close();
    await undo();
    onOpenChange(false);
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(o) : void cancel())}
      // Wider than the default: the client fields sit side by side, and the return address reads in full.
      size="md"
      title={another ? `Connect another ${card.name} account` : `Connect ${card.name}`}
      description={`Choose how Ops AI signs in to ${card.name}, then allow access.`}
      data-testid="connect-window"
      footer={
        <>
          <Button variant="outline" onClick={() => void cancel()} data-testid="connect-window-cancel">
            Cancel
          </Button>
          <LoadingButton isLoading={waiting} onClick={() => void authorize()} data-testid="connect-window-authorize">
            <ExternalLink />
            {waiting ? 'Connecting…' : `Authorize with ${card.name}`}
          </LoadingButton>
        </>
      }
    >
      <Form {...form}>
      <div className="flex min-w-0 flex-col gap-4">
        {reusing ? (
          <div className="flex flex-col gap-1 rounded-md border p-3 text-sm" data-testid="connect-window-reuse">
            <p>
              Continuing with <span className="font-medium">{existing?.name ?? `${card.name}’s app credential`}</span>
            </p>
            <p className="text-xs text-muted-foreground">{chosen === 'own' ? 'Your own app' : 'Ops AI’s app'}</p>
            <Button type="button" variant="link" size="sm" className="h-auto justify-start p-0" onClick={() => setNewClient(true)} data-testid="connect-window-new-client">
              Use a new client of your own
            </Button>
          </div>
        ) : newClient ? null : !managed ? (
          <div className="flex flex-col gap-1 rounded-md border p-3 text-sm" data-testid="connect-window-own-only">
            <p>{card.name} signs in with your team’s own app: register one with {card.name} and give its client ID and secret.</p>
            {card.mayManage && <p className="text-xs text-muted-foreground">Ops AI’s app is not set up for this install. An install admin sets it in the install’s configuration.</p>}
          </div>
        ) : (
          <Tabs value={app} onValueChange={(v) => setApp(v as App)}>
            <TabsList className="w-full" data-testid="connect-window-app">
              {/* Ops AI's app is offered once an account admin has set it up for this plugin. */}
              <TabsTrigger value="platform" className="flex-1" disabled={!plugin.platformApp} data-testid="connect-window-app-platform">
                Ops AI’s app
              </TabsTrigger>
              <TabsTrigger value="own" className="flex-1" data-testid="connect-window-app-own">
                Your own app
              </TabsTrigger>
            </TabsList>
          </Tabs>
        )}

        {needed.map(setting)}

        {typing && (
          <div className="flex flex-col gap-3" data-testid="connect-window-client">
            <div className="grid gap-3 sm:grid-cols-2">
              <FormTextField control={form.control} name="clientId" label="Client ID" testId="connect-window-client-id" />
              <FormTextField control={form.control} name="clientSecret" label="Client secret" type="password" hint="Sealed when saved; never shown again." testId="connect-window-client-secret" />
            </div>
            {kinds.redirectUri && (
              <FormField id="connect-return" label="Return address" hint={`Register it on your ${card.name} app.`}>
                <div className="flex min-w-0 items-center gap-1">
                  <Input id="connect-return" readOnly value={kinds.redirectUri} className="font-mono text-xs" />
                  <CopyButton text={kinds.redirectUri} />
                </div>
              </FormField>
            )}
            {card.docsUrl && (
              <a href={card.docsUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm underline-offset-4 hover:underline">
                Where to find these for {card.name} <ExternalLink className="size-3.5" />
              </a>
            )}
          </div>
        )}

        {plugin.scopes.length > 0 && (
          <div className="flex flex-col gap-1.5" data-testid="connect-window-scopes">
            <p className="text-sm text-muted-foreground">{chosen === 'own' ? `Your ${card.name} app asks for:` : `Ops AI’s ${card.name} app gets access to:`}</p>
            <div className="flex flex-wrap gap-1.5">
              {plugin.scopes.map((s) => (
                <Badge key={s} variant="outline" className="font-mono">
                  {s}
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">Asking for more later needs another sign-in.</p>
          </div>
        )}

        <Collapsible open={more} onOpenChange={setMore}>
          <CollapsibleTrigger asChild>
            <Button type="button" variant="ghost" size="sm" className="h-auto gap-1.5 px-0 text-muted-foreground hover:bg-transparent hover:text-foreground" data-testid="connect-window-more">
              {more ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              More options
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="flex flex-col gap-4 pt-3">
            {tuned.map(setting)}
            <FormTextField control={form.control} name="accountName" label="Account name" optional placeholder={suggested} hint="Steps and tools pick an account by this name." testId="connect-window-name" />
            <label className="flex items-start gap-2" data-testid="connect-window-team">
              <Checkbox checked={team} onCheckedChange={(v) => setTeam(v === true)} className="mt-0.5" />
              <span className="grid gap-1">
                <span className="text-sm">Team account</span>
                <span className="text-xs text-muted-foreground">Anyone in {current?.name ?? 'the team'} can run tools as this account. Off, it is yours alone.</span>
              </span>
            </label>
          </CollapsibleContent>
        </Collapsible>

        {waiting && <p className="text-sm">Allow access in the {card.name} window that opened.</p>}
        {error && (
          <p className="text-sm text-destructive" role="alert" data-testid="connect-window-error">
            {error}
          </p>
        )}
      </div>
      </Form>
    </DialogShell>
  );
}
