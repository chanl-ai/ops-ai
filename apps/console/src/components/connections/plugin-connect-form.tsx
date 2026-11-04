'use client';

import * as React from 'react';
import { Copy } from 'lucide-react';
import { toast } from 'sonner';

import { EnvSection } from '@/components/connections/env-section';
import { WhoSignsIn, type SignIn } from '@/components/connections/who-signs-in';
import { CONNECTED_MESSAGE, openSignIn, type ConnectedMessage } from '@/components/connections/sign-in';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  type SystemCard,
  type TeamPluginBody,
  useDeleteConnection,
  useSetTeamPlugin,
  useStartSignIn,
  useTestEnvironment,
} from '@/hooks/systems-queries';
import {
  complete,
  draftFor,
  initialState,
  keyed,
  leading,
  ordered,
  pluginGroups,
  reduce,
  toSave,
  turnOnBody,
  type App,
  type EnvDraft,
  type Environment,
  type FieldGroups,
  type Kind,
  type Kinds,
} from '@/lib/connect-plan';
import { cn } from '@/lib/utils';

type PluginInfo = NonNullable<SystemCard['plugin']>;

const message = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong');

/** The connect dialog's form for a plugin: its sign-in kind, the platform's app or the team's own, and each environment. */
export function PluginConnectForm({
  open,
  card,
  kinds,
  first,
  onClose,
}: {
  open: boolean;
  card: SystemCard;
  kinds: Kinds;
  first?: Environment;
  onClose: () => void;
}) {
  const plugin = card.plugin as PluginInfo;
  const offered = kinds.kinds.filter((k) => plugin.kinds.includes(k.id));
  const [kindId, setKindId] = React.useState(card.authKind ?? plugin.kinds[0]);
  const kind = offered.find((k) => k.id === kindId) ?? offered[0];
  const [app, setApp] = React.useState<App>(plugin.platformApp ? 'platform' : 'own');
  // Whose account calls use, asked only before the team's connection exists and when the plugin offers a choice.
  const offeredWho = plugin.signIn ?? ['team'];
  const [who, setWho] = React.useState<SignIn>((offeredWho[0] as SignIn | undefined) ?? 'team');
  const asksWho = kind.perPerson && offeredWho.length > 1 && !card.connectionId;
  const groups = pluginGroups(kind, kinds, plugin, app);
  const teamFields = plugin.settings.filter((s) => !s.perEnvironment && !s.locked);
  const [team, setTeam] = React.useState<Record<string, string>>(() => Object.fromEntries(teamFields.map((s) => [s.name, s.default ?? ''])));
  const sectionsOf = (g: FieldGroups) => Object.fromEntries(keyed(kinds).map((e) => [e.id, draftFor(e.id, g)]));
  const setOnConnection = keyed(kinds)
    .map((e) => e.id)
    .filter((id) => card.environments[id]?.set);
  const [state, dispatch] = React.useReducer(reduce, initialState(sectionsOf(groups), card.connectionId ?? null, setOnConnection));
  // The sign-in window open, the environment it signs in, and whether Save opened it, so the dialog closes once it works.
  const opened = React.useRef<{ window: Window | null; environment: Environment; closes: boolean } | null>(null);
  const turnedOn = React.useRef(plugin.teamOn);

  const name = card.name;
  const close = React.useRef(onClose);
  React.useEffect(() => {
    close.current = onClose;
  }, [onClose]);
  const setTeamPlugin = useSetTeamPlugin();
  const test = useTestEnvironment();
  const signIn = useStartSignIn();
  const remove = useDeleteConnection();

  // One environment in the Connect window; the other is set up from the app page's Settings.
  const envs = ordered(kinds, first).slice(0, 1);
  const ready = envs.map((e) => e.id).filter((id) => complete(state.sections[id], groups));

  const reshape = (nextKind: Kind, nextApp: App) =>
    dispatch({ type: 'reset', sections: sectionsOf(pluginGroups(nextKind, kinds, plugin, nextApp)), connectionId: state.connectionId });

  const runTest = React.useCallback(
    async (connectionId: string, env: Environment): Promise<boolean> => {
      const tested = await test.mutateAsync({ connectionId, environment: env });
      const envs = tested.environments as Record<string, { health?: EnvDraft['health'] }>;
      const health = envs[env]?.health ?? tested.health ?? null;
      dispatch({ type: 'tested', environment: env, health });
      return health?.status === 'ok';
    },
    [test],
  );

  React.useEffect(() => {
    const onMessage = (e: MessageEvent<ConnectedMessage>) => {
      const waiting = opened.current;
      if (e.origin !== window.location.origin || e.data?.type !== CONNECTED_MESSAGE || !waiting || e.source !== waiting.window) return;
      opened.current = null;
      dispatch({ type: 'signed-in', environment: waiting.environment });
      dispatch({ type: 'start', environment: waiting.environment, status: 'testing' });
      runTest(e.data.connectionId, waiting.environment)
        .then((ok) => {
          if (!ok || !waiting.closes) return;
          dispatch({ type: 'done' });
          toast.success(`${name} is on for the team`);
          close.current();
        })
        .catch((err) => dispatch({ type: 'failed', environment: waiting.environment, message: message(err) }));
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [runTest, name]);

  /** Turns the plugin on for one environment with its section's values; the answer names its connection. */
  const turnOn = async (env: Environment): Promise<string> => {
    const draft = state.sections[env];
    const view = await setTeamPlugin.mutateAsync({
      path: { plugin_id: card.pluginId ?? '' },
      body: turnOnBody(kind, plugin, app, draft, team, !state.connectionId, asksWho ? who : undefined) as TeamPluginBody,
    });
    const id = String(view.connectionId ?? '');
    if (!state.connectionId) dispatch({ type: 'created', connectionId: id, made: !turnedOn.current });
    dispatch({
      type: 'saved',
      environment: env,
      secretSet: Object.fromEntries(Object.entries(draft.secrets).map(([k, v]) => [k, Boolean(v) || draft.secretSet[k]])),
    });
    return id;
  };

  const startSignIn = async (id: string, env: Environment, closes = false) => {
    const start = await signIn.mutateAsync({ connectionId: id, environment: env, account: 'team' });
    opened.current = { window: openSignIn(start, id), environment: env, closes };
    dispatch({ type: 'signing-in' });
  };

  const sectionTest = async (env: Environment) => {
    if (state.busy) return;
    dispatch({ type: 'start', environment: env, status: 'testing' });
    try {
      const id = await turnOn(env);
      if (kind.signsIn) await startSignIn(id, env);
      else await runTest(id, env);

    } catch (e) {
      dispatch({ type: 'failed', environment: env, message: message(e) });
    }
  };

  const finish = async () => {
    if (state.busy) return;
    // Save completes one environment, production when it is ready, and signs in for that same one.
    const env = leading(kinds, ready) ?? envs[0].id;
    const saving = toSave(state, ready, env);
    dispatch({ type: 'start', environment: env, status: 'saving' });
    try {
      let id = state.connectionId ?? '';
      for (const e of saving) id = await turnOn(e);
      // An account signed in through this dialog already: Save does not open a second window for it.
      if (kind.signsIn && !state.signedIn.includes(env)) return void (await startSignIn(id, env, true));
      dispatch({ type: 'done' });
      toast.success(`${card.name} is on for the team`);
      onClose();
    } catch (e) {
      dispatch({ type: 'failed', environment: env, message: message(e) });
    }
  };

  /** Cancel removes what this dialog made: the connection, then the team's switch, which forgets the removed connection. */
  const cancel = async () => {
    opened.current?.window?.close();
    opened.current = null;
    if (state.created && state.connectionId) {
      try {
        await remove.mutateAsync(state.connectionId);
        await setTeamPlugin.mutateAsync({
          path: { plugin_id: card.pluginId ?? '' },
          body: { enabled: false, environment: envs[0].id as TeamPluginBody['environment'] },
        });
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
      title={`Connect ${card.name}`}
      description={card.description ?? 'It is tested before it is called working.'}
      data-testid="connect-dialog"
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => void cancel()} data-testid="connect-cancel">
            {state.phase === 'signing-in' ? 'Close' : 'Cancel'}
          </Button>
          <LoadingButton
            type="button"
            onClick={() => void finish()}
            isLoading={state.busy && !Object.values(state.sections).some((d) => d.status === 'testing')}
            disabled={!ready.length || state.busy}
            data-testid="connect-submit"
          >
            {kind.signsIn ? 'Save and connect the team account' : 'Save'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-5">
        <div className="grid gap-4 sm:grid-cols-2">
          {offered.length > 1 && (
            <FormField id="plugin-kind" label="How it signs in">
              <Select
                value={kind.id}
                onValueChange={(v) => (setKindId(v), reshape(offered.find((k) => k.id === v) ?? kind, app))}
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
            <FormField key={s.name} id={`plugin-${s.name}`} label={s.label} optional={Boolean(s.default)}>
              <Input id={`plugin-${s.name}`} value={team[s.name] ?? ''} onChange={(e) => setTeam((t) => ({ ...t, [s.name]: e.target.value }))} />
            </FormField>
          ))}
        </div>

        {asksWho && <WhoSignsIn value={who} onChange={setWho} offered={offeredWho} />}

        {kind.signsIn && (
          <div className="flex flex-col gap-3">
            <RadioGroup
              value={app}
              onValueChange={(v) => (setApp(v as App), reshape(kind, v as App))}
              className="grid gap-2 sm:grid-cols-2"
              aria-label="Which app the team signs in with"
              data-testid="plugin-app"
            >
              {(
                [
                  {
                    value: 'platform',
                    label: 'The platform’s app',
                    hint: 'Set up once by an account admin. Nothing to register.',
                    disabled: !plugin.platformApp,
                  },
                  { value: 'own', label: 'Our own app', hint: `Register an app with ${card.name} and enter its client ID and secret.`, disabled: false },
                ] as const
              ).map((o) => (
                <label
                  key={o.value}
                  htmlFor={`app-${o.value}`}
                  className={cn(
                    'flex items-start gap-3 rounded-md border p-3',
                    o.disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
                    app === o.value && 'border-primary bg-primary/5',
                  )}
                >
                  <RadioGroupItem value={o.value} id={`app-${o.value}`} disabled={o.disabled} className="mt-0.5" />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{o.label}</span>
                    <span className="block text-xs text-muted-foreground">{o.disabled ? 'No account admin has set it up yet.' : o.hint}</span>
                  </span>
                </label>
              ))}
            </RadioGroup>
            {app === 'own' && kinds.redirectUri && (
              <div className="flex min-w-0 flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Return address to register:</span>
                <code className="min-w-0 break-all">{kinds.redirectUri}</code>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => void navigator.clipboard.writeText(kinds.redirectUri ?? '').then(() => toast.success('Copied'))}
                  aria-label="Copy the return address"
                >
                  <Copy />
                </Button>
              </div>
            )}
            {plugin.scopes.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="text-muted-foreground">It asks for:</span>
                {plugin.scopes.map((s) => (
                  <Badge key={s} variant="outline">
                    {s}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}

        {envs.map(({ id: env, label }) => (
          <EnvSection
            key={env}
            env={env}
            label={label}
            draft={state.sections[env]}
            groups={groups}
            busy={state.busy}
            canTest={complete(state.sections[env], groups)}
            testLabel={kind.signsIn ? 'Sign in and test' : 'Run test'}
            onSetting={(n, v) => dispatch({ type: 'setting', environment: env, name: n, value: v })}
            onSecret={(n, v) => dispatch({ type: 'secret', environment: env, name: n, value: v })}
            onTest={() => void sectionTest(env)}
          />
        ))}

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
