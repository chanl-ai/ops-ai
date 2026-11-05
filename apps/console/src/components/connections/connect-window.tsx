'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';

import { AppCredentialPicker } from '@/components/connections/app-credential-picker';
import { appHref } from '@/components/connections/systems-grid';
import { useSignInWindow } from '@/components/connections/sign-in';
import { isSignInPlace, SignInPlace } from '@/components/connections/sign-in-place';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormTextField } from '@/components/shared/form-text-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Form } from '@/components/ui/form';
import { useTeam } from '@/hooks/use-team';
import {
  type AccountBody,
  type SystemCard,
  type TeamAppBody,
  useAccountDetail,
  useAddAccount,
  useDeleteAccount,
  useSetTeamApp,
  useStartSignIn,
  useTestAccount,
} from '@/hooks/systems-queries';
import { draftFor, newAccountBody, pluginGroups, turnOnBody, type KindField, type Kinds } from '@/lib/connect-plan';
import { fieldErrors, schemaForFields } from '@/lib/field-schema';

/** A plugin the Connect window connects: one that signs in with an account, through Ops AI's app or the team's own. */
export function connectsInWindow(card: SystemCard, kinds: Kinds | undefined): boolean {
  const kind = kinds?.kinds.find((k) => k.id === (card.authKind ?? card.plugin?.kinds[0]));
  return card.kind === 'plugin' && Boolean(kind?.signsIn);
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** `wanted`, or `wanted 2`, `wanted 3`… once an account of the app has that name; names compare without case. */
function freeName(wanted: string, taken: string[]): string {
  const used = new Set(taken.map((t) => t.trim().toLowerCase()));
  if (!used.has(wanted.toLowerCase())) return wanted;
  let n = 2;
  while (used.has(`${wanted} ${n}`.toLowerCase())) n++;
  return `${wanted} ${n}`;
}

/**
 * The one Connect window for an app that signs in with an account: which app credential it signs in with (Ops AI's
 * app or one the team made under Credentials, the account's own when it has one), the access it asks for, then
 * Authorize. No client is typed here. The sign-in
 * window opens on the click and closes once access is allowed; the account's first test then runs in the background.
 * `another` adds a second named account of an app the team has connected; `sandbox` adds its sandbox account, which
 * test runs use, asking what the first connect asked. `credential` starts it on one app credential (null for Ops AI's
 * app), as Connect account on a credential's page does. Cancel removes what the window made.
 */
export function ConnectWindow({
  card,
  kinds,
  another = false,
  sandbox = false,
  credential,
  taken = [],
  open,
  onOpenChange,
}: {
  card: SystemCard;
  kinds: Kinds;
  another?: boolean;
  sandbox?: boolean;
  credential?: string | null;
  /** The app's account names already used, so the name it suggests is free. */
  taken?: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const setTeamApp = useSetTeamApp();
  const addAccount = useAddAccount();
  const start = useStartSignIn();
  const remove = useDeleteAccount();
  const test = useTestAccount();
  const { team: current } = useTeam();
  const plugin = card.plugin;
  const kind = kinds.kinds.find((k) => k.id === (card.authKind ?? plugin?.kinds[0]));
  // Another account of the app: added beside the default one, never through the app's turn-on.
  const adding = another || sandbox;

  // The app credential the team's connection already signs in with, as the app's card names it; a sandbox signs in
  // elsewhere, so it picks its own.
  const reusing = Boolean(card.connectionId) && !sandbox;
  // Ops AI's own client exists only where the install set it up; without it a team credential is the one way in.
  const managed = card.managedClient ?? Boolean(plugin?.platformApp);
  const held = reusing && card.credential?.type === 'own' ? (card.credential.id ?? null) : null;
  const [client, setClient] = React.useState<string | null>(credential !== undefined ? credential : held);
  // The plugin's own settings (Salesforce's sign-in address) when the app is first connected; kept after. A sandbox
  // asks the ones each account keeps its own, as the team's settings stay the app's.
  // Another account is asked where it signs in, as every Salesforce org has its own address; a turn-on again asks nothing.
  const places = (plugin?.settings ?? []).filter(isSignInPlace);
  const asked = reusing ? (another ? places : []) : (plugin?.settings ?? []).filter((x) => !x.locked && (!sandbox || x.perAccount));
  const fields: KindField[] = asked.filter((x) => !isSignInPlace(x)).map((x) => ({ name: x.name, label: x.label, secret: x.secret, required: !x.default, advanced: Boolean(x.default), default: x.default }));
  const schema = schemaForFields(fields);
  const form = useForm<Record<string, string>>({
    defaultValues: { accountName: '', ...Object.fromEntries((plugin?.settings ?? []).map((x) => [x.name, x.default ?? ''])) },
  });
  // Another account starts from where the app's default account signs in.
  const first = useAccountDetail(another && card.connectionId ? { appId: card.id, accountId: card.connectionId } : null);
  React.useEffect(() => {
    const held = (first.data?.pluginSettings ?? {}) as Record<string, unknown>;
    for (const x of places) if (typeof held[x.name] === 'string' && held[x.name]) form.setValue(x.name, String(held[x.name]));
  }, [first.data]);
  // Settings with a default wait under More options, so the default path stays the app credential and Authorize.
  const needed = fields.filter((f) => !f.advanced);
  const tuned = fields.filter((f) => f.advanced);

  // Whose account it is and its name sit under More options; another account or a sandbox opens with them showing.
  const [more, setMore] = React.useState(another || sandbox);
  const [team, setTeam] = React.useState(true);
  const suggested = freeName(sandbox ? `${card.name} sandbox` : another ? `${card.name} · second account` : `${card.name} · ${current?.name ?? 'Team'}`, taken);

  const [waiting, setWaiting] = React.useState(false);
  // The account a sign-in window was closed on before access was allowed: Try again signs it in again, as it is.
  const [closedOn, setClosedOn] = React.useState<string | null>(null);
  const signingIn = React.useRef<string | null>(null);
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
      test.mutate({ appId: card.id, accountId: m.connectionId });
      router.push(appHref(card));
    },
    onClosed: () => {
      setWaiting(false);
      setClosedOn(signingIn.current);
      setError(`The window was closed before access was allowed. Try again to open it once more.`);
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
      if (m.id) await remove.mutateAsync({ appId: card.id, accountId: m.id });
      if (m.turnedOn) await setTeamApp.mutateAsync({ appId: card.id, body: { enabled: false, sandbox: false } });
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
    if (!managed && client === null) {
      setError(`Pick the auth config ${card.name} signs in with.`);
      return;
    }
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
      const draft = draftFor(pluginGroups(kind, kinds, plugin));
      // Only what the window asked goes out: a field it did not show holds its default, which would replace the address
      // the app's account already signs in at.
      for (const k of Object.keys(draft.settings)) if (!asked.some((a) => a.name === k)) delete draft.settings[k];
      for (const x of asked.filter((a) => a.perAccount)) draft.settings[x.name] = values[x.name] ?? '';
      const teamSettings = Object.fromEntries(asked.filter((a) => !a.perAccount).map((a) => [a.name, values[a.name] ?? '']));
      const accountName = (values.accountName ?? '').trim() || suggested;
      const offered = team ? (plugin.signIn.includes('person_or_team') ? 'person_or_team' : undefined) : plugin.signIn.includes('person') ? 'person' : undefined;
      let id: string;
      if (adding) {
        const body = newAccountBody(kind, plugin, client, draft, accountName, sandbox, offered) as AccountBody;
        const account = await addAccount.mutateAsync({ appId: card.id, body });
        id = account.id;
        made.current = { id, turnedOn: false };
      } else {
        const body = { ...turnOnBody(kind, plugin, client, draft, teamSettings, !card.connectionId, offered), accountName } as TeamAppBody;
        const view = await setTeamApp.mutateAsync({ appId: card.id, body });
        id = String(view.connectionId ?? card.connectionId ?? '');
        made.current = { id: card.connectionId ? null : id, turnedOn: true };
      }
      signingIn.current = id;
      const s = await start.mutateAsync({ appId: card.id, accountId: id, account: team ? 'team' : 'self' });
      w.go(s, { appId: card.id, accountId: id });
    } catch (e) {
      w.fail(message(e));
      setError(message(e));
      void undo().finally(() => setWaiting(false));
    }
  };

  /** Try again after the window was closed: a new window, signing in the account already made. */
  const again = async (id: string) => {
    const w = signIn.open(card.name, card.logo);
    if (!w) return;
    setError(null);
    setClosedOn(null);
    setWaiting(true);
    try {
      signingIn.current = id;
      const s = await start.mutateAsync({ appId: card.id, accountId: id, account: team ? 'team' : 'self' });
      w.go(s, { appId: card.id, accountId: id });
    } catch (e) {
      w.fail(message(e));
      setError(message(e));
      setWaiting(false);
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
      size="md"
      title={sandbox ? `Add a ${card.name} sandbox account` : another ? `Connect another ${card.name} account` : `Connect ${card.name}`}
      description={`Choose how Ops AI signs in to ${card.name}, then allow access.`}
      data-testid="connect-window"
      footer={
        <>
          <Button variant="outline" onClick={() => void cancel()} data-testid="connect-window-cancel">
            Cancel
          </Button>
          <LoadingButton isLoading={waiting} onClick={() => void (closedOn ? again(closedOn) : authorize())} data-testid="connect-window-authorize">
            <ExternalLink />
            {waiting ? 'Connecting…' : closedOn ? 'Try again' : 'Connect'}
          </LoadingButton>
        </>
      }
    >
      <Form {...form}>
      <div className="flex min-w-0 flex-col gap-4">
        <AppCredentialPicker app={card.id} value={client} onChange={setClient} platform={managed && Boolean(plugin.platformApp)} id="connect-window-app" testId="connect-window-app" />

        {asked.filter(isSignInPlace).map((x) => (
          <SignInPlace key={x.name} setting={x} value={form.watch(x.name) ?? ''} onChange={(v) => form.setValue(x.name, v)} testId={`connect-window-place-${x.name}`} />
        ))}

        {needed.map(setting)}

        {plugin.scopes.length > 0 && (
          <div className="flex flex-col gap-1.5" data-testid="connect-window-scopes">
            <p className="text-sm text-muted-foreground">{client ? `Your ${card.name} app asks for:` : `Ops AI’s ${card.name} app gets access to:`}</p>
            <div className="flex flex-wrap gap-1.5">
              {plugin.scopes.map((s) => (
                <Badge key={s.id} variant="outline" title={s.id}>
                  {s.label}
                </Badge>
              ))}
            </div>
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
