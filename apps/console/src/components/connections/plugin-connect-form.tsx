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
  useAppCredential,
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
  const [accountName, setAccountName] = React.useState(`${card.name} test account`);
  // Whose account calls use, asked only before the team's default account exists and when the plugin offers a choice.
  const offeredWho = plugin.signIn ?? ['team'];
  const [who, setWho] = React.useState<SignIn>((offeredWho[0] as SignIn | undefined) ?? 'team');
  const asksWho = !sandbox && kind.perPerson && offeredWho.length > 1 && !card.connectionId;
  // Editing the default account: its keys are saved, and a blank field keeps its value. A new sandbox has none yet.
  const editing = !sandbox && Boolean(card.connectionId);
  // A setting asked on the auth config is the picked config's when it sets one, edited there; an account on a config
  // that leaves it unset (Ops AI's app) keeps its own, asked here.
  const picked = useAppCredential(client ?? '');
  const onConfig = (picked.data?.settings ?? {}) as Record<string, unknown>;
  // Until the picked config answers, its fields are not shown: one it sets would otherwise be asked for a moment.
  const ownSettings = plugin.settings.filter((x) => x.asked !== 'config' || !client || (Boolean(picked.data) && (onConfig[x.name] === undefined || onConfig[x.name] === '')));
  const groupsFor = (k: Kind) => pluginGroups(k, kinds, { ...plugin, settings: ownSettings }, editing);
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
  // Whether a sign-in window Sign in and test opened is still waiting on access.
  const opened = React.useRef(false);
  const turnedOn = React.useRef(plugin.teamOn);
  // Whether keys were typed since the sandbox account was made.
  const typedSince = React.useRef(false);

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
      opened.current = false;
      if (waiting) dispatch({ type: 'failed', message: why });
    },
    onClosed: () => {
      const waiting = opened.current;
      opened.current = false;
      if (waiting) dispatch({ type: 'failed', message: 'The window was closed before access was allowed. Sign in and test to try once more.' });
    },
    onConnected: (m) => {
      if (!opened.current) return;
      opened.current = false;
      dispatch({ type: 'signed-in' });
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

  const startSignIn = async (w: SignInWindow, id: string): Promise<void> => {
    // Try again in the window starts the same sign-in again, on the account already made.
    w.retry(() =>
      void startSignIn(w, id).catch((e: unknown) => {
        w.fail(message(e));
        dispatch({ type: 'failed', message: message(e) });
      }),
    );
    const start = await signIn.mutateAsync({ ...ref(id), account: 'team' });
    opened.current = true;
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

  /**
   * Save saves and stops: it never opens a sign-in, even for a kind that signs in. Signing in is its own action (Sign
   * in and test here, Sign in on the account's row, or each person's Connectors › Mine), so an admin saving the team's
   * setting is never asked to connect an account of their own.
   */
  const finish = async () => {
    if (state.busy) return;
    // A team setting typed on an app already made is saved with the account.
    const teamTyped = Boolean(card.connectionId) && Object.entries(team).some(([k, v]) => v.trim() !== '' && v !== first[k]);
    const saving = teamTyped || state.draft.status === 'dirty' || !state.saved || !state.connectionId;
    dispatch({ type: 'start', status: 'saving' });
    try {
      if (saving) await write();
      dispatch({ type: 'done' });
      const next = !kind.signsIn
        ? undefined
        : card.signIn === 'team'
          ? `Sign the team account in from the Accounts tab when you are ready.`
          : 'Members connect their own account from Connectors › Mine.';
      toast.success(sandbox ? `${accountName.trim()} is saved` : `Saved. ${card.name} is on for the team`, { description: next });
      onClose();
    } catch (e) {
      dispatch({ type: 'failed', message: message(e) });
    }
  };

  /** Cancel removes what this dialog made: the account, then for a first turn-on the team's switch. */
  const cancel = async () => {
    signInWindow.close();
    opened.current = false;
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
      size="md"
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
            {kind.signsIn ? 'Save' : 'Connect'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-5">
        <div className="grid gap-4">
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
              card={card}
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

        {/* No sign-in and no account setting: nothing to type or test here. */}
        {(kind.id !== 'none' || groups.main.length > 0) && (
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
        )}

        {state.phase === 'signing-in' && (
          <p className="rounded-md border p-3 text-sm" data-testid="connect-signing-in">
            Finish signing in to {card.name} in the window that opened.
          </p>
        )}
        {state.error && (
          <p className="text-sm text-destructive-text" role="alert" data-testid="connect-error">
            {state.error}
          </p>
        )}
      </div>
    </DialogShell>
  );
}
