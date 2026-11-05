'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { AccountFields } from '@/components/connections/account-fields';
import { AppCredentialPicker } from '@/components/connections/app-credential-picker';
import { WhoSignsIn, type SignIn } from '@/components/connections/who-signs-in';
import { useSignInWindow, type SignInWindow } from '@/components/connections/sign-in';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  type AccountBody,
  type AccountDetail,
  type SystemCard,
  type TeamAppBody,
  useAddAccount,
  useDeleteAccount,
  useSetTeamApp,
  useStartSignIn,
  useTestAccount,
} from '@/hooks/systems-queries';
import {
  complete,
  draftFor,
  initialState,
  newAccountBody,
  pluginGroups,
  reduce,
  turnOnBody,
  type Kind,
  type Kinds,
  type SavedAccount,
} from '@/lib/connect-plan';
import type { AccountRef } from '@/lib/types/connections';

type PluginInfo = NonNullable<SystemCard['plugin']>;

const message = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong');

/**
 * The connect dialog's form for a plugin's app: its sign-in kind, the app credential it signs in with (Ops AI's app or
 * one the team made under Credentials), and the account's keys. `sandbox` adds the app's sandbox account, which test
 * runs use, with the same keys asked.
 */
export function PluginConnectForm({
  open,
  card,
  kinds,
  detail,
  sandbox = false,
  onClose,
}: {
  open: boolean;
  card: SystemCard;
  kinds: Kinds;
  /** The app's default account when it has one: its saved settings fill the fields, its sealed secrets read as set. */
  detail?: AccountDetail | null;
  sandbox?: boolean;
  onClose: () => void;
}) {
  const plugin = card.plugin as PluginInfo;
  const offered = kinds.kinds.filter((k) => plugin.kinds.includes(k.id));
  const [kindId, setKindId] = React.useState(card.authKind ?? plugin.kinds[0]);
  const kind = offered.find((k) => k.id === kindId) ?? offered[0];
  // The default account keeps the app credential it has until another is picked; a new sandbox starts on Ops AI's app.
  const [client, setClient] = React.useState<string | null>(!sandbox && card.credential?.type === 'own' ? (card.credential.id ?? null) : null);
  const [accountName, setAccountName] = React.useState(`${card.name} sandbox`);
  // Whose account calls use, asked only before the team's default account exists and when the plugin offers a choice.
  const offeredWho = plugin.signIn ?? ['team'];
  const [who, setWho] = React.useState<SignIn>((offeredWho[0] as SignIn | undefined) ?? 'team');
  const asksWho = !sandbox && kind.perPerson && offeredWho.length > 1 && !card.connectionId;
  // Editing the default account: its keys are saved, and a blank field keeps its value. A new sandbox has none yet.
  const editing = !sandbox && Boolean(card.connectionId);
  const groupsFor = (k: Kind) => pluginGroups(k, kinds, plugin, editing);
  // What the account saved: its own settings and which of the plugin's secrets are set. The plugin's settings it keeps
  // its own (a sign-in address) start blank, and a blank one keeps its value.
  const saved: SavedAccount | null =
    editing && detail ? { settings: detail.settings, secrets: Object.fromEntries(Object.entries(detail.pluginSecrets ?? {}).map(([k, v]) => [k, { set: v }])) } : null;
  // A sandbox is one more account of the app; the team's settings stay the app's.
  const teamFields = sandbox ? [] : plugin.settings.filter((s) => !s.perAccount && !s.locked);
  const savedTeam = plugin.values ?? {};
  // The team's settings start as saved; one the app does not send back starts blank and keeps its value.
  const [first] = React.useState<Record<string, string>>(() =>
    Object.fromEntries(teamFields.map((s) => [s.name, savedTeam[s.name] != null ? String(savedTeam[s.name]) : card.connectionId ? '' : (s.default ?? '')])),
  );
  const [team, setTeam] = React.useState(first);
  const [state, dispatch] = React.useReducer(reduce, initialState(draftFor(groupsFor(kind), saved), editing ? (card.connectionId ?? null) : null, editing));
  // The sign-in window open, and whether Save opened it, so the dialog closes once it works.
  const opened = React.useRef<{ closes: boolean } | null>(null);
  const turnedOn = React.useRef(plugin.teamOn);
  // Whether keys were typed since the sandbox account was made.
  const typedSince = React.useRef(false);

  const name = card.name;
  const close = React.useRef(onClose);
  React.useEffect(() => {
    close.current = onClose;
  }, [onClose]);
  const setTeamApp = useSetTeamApp();
  const addAccount = useAddAccount();
  const test = useTestAccount();
  const signIn = useStartSignIn();
  const remove = useDeleteAccount();

  const groups = groupsFor(kind);
  // A kind that signs in or fetches a token names its OAuth client: Ops AI's app, or one of the team's credentials.
  const picks = kind.signsIn || kind.holdsToken;
  const ready = complete(state.draft, groups) && (!sandbox || Boolean(accountName.trim())) && (!picks || Boolean(plugin.platformApp) || client !== null);
  const ref = (accountId: string): AccountRef => ({ appId: card.id, accountId });

  const reshape = (nextKind: Kind) => {
    typedSince.current = true;
    dispatch({ type: 'reset', draft: draftFor(groupsFor(nextKind), saved), connectionId: state.connectionId });
  };

  const runTest = React.useCallback(
    async (accountId: string): Promise<boolean> => {
      const tested = await test.mutateAsync({ appId: card.id, accountId });
      const health = tested.health ?? null;
      dispatch({ type: 'tested', health });
      return health?.status === 'ok';
    },
    [card.id, test],
  );

  const signInWindow = useSignInWindow({
    onFailed: (why) => {
      const waiting = opened.current;
      opened.current = null;
      if (waiting) dispatch({ type: 'failed', message: why });
    },
    onConnected: (m) => {
      const waiting = opened.current;
      if (!waiting) return;
      opened.current = null;
      dispatch({ type: 'signed-in' });
      if (waiting.closes) {
        // Save closes once access is allowed; the test runs after, and a failure shows on the account's row.
        dispatch({ type: 'done' });
        toast.success(sandbox ? `${accountName.trim()} is connected` : `${name} is on for the team`);
        void test.mutateAsync(ref(m.connectionId)).catch(() => undefined);
        close.current();
        return;
      }
      dispatch({ type: 'start', status: 'testing' });
      runTest(m.connectionId).catch((err) => dispatch({ type: 'failed', message: message(err) }));
    },
  });

  /**
   * Saves the account's keys: the team's default account through the app's turn-on, or a new sandbox account of the
   * app, made once and then kept. Answers the account's id.
   */
  const write = async (): Promise<string> => {
    const draft = state.draft;
    let id: string;
    if (sandbox) {
      // An account's plugin settings and app are given when it is made, so keys typed after are a new account; the
      // typed values stay in the draft for that.
      if (state.connectionId && !typedSince.current) return state.connectionId;
      if (state.connectionId) await remove.mutateAsync(ref(state.connectionId));
      const made = await addAccount.mutateAsync({ appId: card.id, body: newAccountBody(kind, plugin, client, draft, accountName.trim(), true) as AccountBody });
      typedSince.current = false;
      dispatch({ type: 'created', connectionId: made.id });
      return made.id;
    } else {
      const view = await setTeamApp.mutateAsync({
        appId: card.id,
        body: turnOnBody(kind, plugin, client, draft, team, !state.connectionId, asksWho ? who : undefined) as TeamAppBody,
      });
      id = String(view.connectionId ?? '');
      if (!state.connectionId) dispatch({ type: 'created', connectionId: id, made: !turnedOn.current });
    }
    dispatch({ type: 'saved', secretSet: Object.fromEntries(Object.entries(draft.secrets).map(([k, v]) => [k, Boolean(v) || draft.secretSet[k]])) });
    return id;
  };

  const startSignIn = async (w: SignInWindow, id: string, closes = false): Promise<void> => {
    // Try again in the window starts the same sign-in again, on the account already made.
    w.retry(() =>
      void startSignIn(w, id, closes).catch((e: unknown) => {
        w.fail(message(e));
        dispatch({ type: 'failed', message: message(e) });
      }),
    );
    const start = await signIn.mutateAsync({ ...ref(id), account: 'team' });
    opened.current = { closes };
    w.go(start, ref(id));
    dispatch({ type: 'signing-in' });
  };

  const sectionTest = async () => {
    if (state.busy) return;
    // A sign-in window opens in the click, before any call, so a pop-up blocker lets it through.
    const w = kind.signsIn ? signInWindow.open(card.name, card.logo) : null;
    if (kind.signsIn && !w) return;
    dispatch({ type: 'start', status: 'testing' });
    try {
      const id = await write();
      if (w) await startSignIn(w, id);
      else await runTest(id);
    } catch (e) {
      w?.fail(message(e));
      dispatch({ type: 'failed', message: message(e) });
    }
  };

  const finish = async () => {
    if (state.busy) return;
    // A team setting typed on an app already made is saved with the account.
    const teamTyped = Boolean(card.connectionId) && Object.entries(team).some(([k, v]) => v.trim() !== '' && v !== first[k]);
    const saving = teamTyped || state.draft.status === 'dirty' || !state.saved || !state.connectionId;
    // A signed-in account saved with nothing typed keeps its sign-in; an account signed in through this dialog
    // already does too. Anything else signs in again, as its app or address may have changed.
    const signs = kind.signsIn && !state.signedIn && saving;
    const w = signs ? signInWindow.open(card.name, card.logo) : null;
    if (signs && !w) return;
    dispatch({ type: 'start', status: 'saving' });
    try {
      const id = saving ? await write() : (state.connectionId ?? '');
      if (w) return void (await startSignIn(w, id, true));
      dispatch({ type: 'done' });
      toast.success(sandbox ? `${accountName.trim()} is saved` : `${card.name} is on for the team`);
      onClose();
    } catch (e) {
      w?.fail(message(e));
      dispatch({ type: 'failed', message: message(e) });
    }
  };

  /** Cancel removes what this dialog made: the account, then for a first turn-on the team's switch. */
  const cancel = async () => {
    signInWindow.close();
    opened.current = null;
    if (state.created && state.connectionId) {
      try {
        await remove.mutateAsync(ref(state.connectionId));
        if (!sandbox) await setTeamApp.mutateAsync({ appId: card.id, body: { enabled: false, sandbox: false } });
      } catch (e) {
        toast.error(`Couldn’t remove what was made for ${card.name}`, { description: message(e) });
      }
    }
    onClose();
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !o && void cancel()}
      size="sm"
      title={sandbox ? `Add a ${card.name} sandbox account` : `Connect ${card.name}`}
      description={card.description ?? undefined}
      data-testid="connect-dialog"
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => void cancel()} data-testid="connect-cancel">
            {state.phase === 'signing-in' ? 'Close' : 'Cancel'}
          </Button>
          <LoadingButton
            type="button"
            onClick={() => void finish()}
            isLoading={state.busy && state.draft.status !== 'testing'}
            disabled={!ready || state.busy}
            data-testid="connect-submit"
          >
            {kind.signsIn ? (sandbox ? 'Save and connect the sandbox account' : 'Save and connect the team account') : 'Save'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-5">
        <div className="grid gap-4 sm:grid-cols-2">
          {sandbox && (
            <FormField id="plugin-account-name" label="Account name" hint="Steps and tools pick an account by this name.">
              <Input id="plugin-account-name" value={accountName} onChange={(e) => setAccountName(e.target.value)} disabled={Boolean(state.connectionId)} data-testid="plugin-account-name" />
            </FormField>
          )}
          {offered.length > 1 && !sandbox && (
            <FormField id="plugin-kind" label="How it signs in">
              <Select
                value={kind.id}
                onValueChange={(v) => (setKindId(v), reshape(offered.find((k) => k.id === v) ?? kind))}
                disabled={Boolean(state.connectionId)}
              >
                <SelectTrigger id="plugin-kind" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {offered.map((k) => (
                    <SelectItem key={k.id} value={k.id}>
                      {k.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
          {teamFields.map((s) => (
            <FormField key={s.name} id={`plugin-${s.name}`} label={s.label} optional={Boolean(s.default) || Boolean(card.connectionId)} hint={card.connectionId ? 'Blank keeps the saved value.' : undefined}>
              <Input id={`plugin-${s.name}`} value={team[s.name] ?? ''} onChange={(e) => setTeam((t) => ({ ...t, [s.name]: e.target.value }))} />
            </FormField>
          ))}
        </div>

        {asksWho && <WhoSignsIn value={who} onChange={setWho} offered={offeredWho} />}

        {picks && (
          <div className="flex flex-col gap-3">
            <AppCredentialPicker
              app={card.id}
              value={client}
              onChange={(c) => ((typedSince.current = true), setClient(c))}
              platform={Boolean(plugin.platformApp)}
              id="plugin-app"
              testId="plugin-app"
            />
            {plugin.scopes.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="text-muted-foreground">It asks for:</span>
                {plugin.scopes.map((s) => (
                  <Badge key={s.id} variant="outline" title={s.id}>
                    {s.label}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}

        <AccountFields
          draft={state.draft}
          groups={groups}
          busy={state.busy}
          canTest={ready}
          testLabel={kind.signsIn ? 'Sign in and test' : 'Run test'}
          onSetting={(n, v) => ((typedSince.current = true), dispatch({ type: 'setting', name: n, value: v }))}
          onSecret={(n, v) => ((typedSince.current = true), dispatch({ type: 'secret', name: n, value: v }))}
          onTest={() => void sectionTest()}
        />

        {state.phase === 'signing-in' && (
          <p className="rounded-md border p-3 text-sm" data-testid="connect-signing-in">
            Finish signing in to {card.name} in the window that opened.
          </p>
        )}
        {state.error && (
          <p className="text-sm text-destructive" role="alert" data-testid="connect-error">
            {state.error}
          </p>
        )}
      </div>
    </DialogShell>
  );
}
