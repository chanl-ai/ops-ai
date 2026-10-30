'use client';

import * as React from 'react';
import { ExternalLink } from 'lucide-react';
import { toast } from 'sonner';

import { CONNECTED_MESSAGE, openSignIn, type ConnectedMessage } from '@/components/connections/sign-in';
import { EnvSection } from '@/components/connections/env-section';
import { PluginConnectForm } from '@/components/connections/plugin-connect-form';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type ConnectionDetail,
  type SystemCard,
  useBindModule,
  useChangeConnection,
  useConnectionDetail,
  useConnectionKinds,
  useCreateConnection,
  useDeleteConnection,
  useSetEnvironment,
  useStartSignIn,
  useTestEnvironment,
} from '@/hooks/systems-queries';
import {
  complete,
  draftFor,
  environmentBody,
  fieldsFor,
  initialState,
  leading,
  ordered,
  planFor,
  reduce,
  type EnvDraft,
  type Environment,
  type Kind,
  type Kinds,
  type SavedEnvironment,
} from '@/lib/connect-plan';
import { cn } from '@/lib/utils';

export type ConnectTarget =
  { kind: 'connection'; connectionId: string } | { kind: 'module'; moduleId: string; name: string } | { kind: 'plugin'; card: SystemCard } | { kind: 'new' };

export type ConnectMode = 'connect' | 'edit' | 'reconnect';

type SignIn = 'team' | 'person' | 'person_or_team';

const WHO: { value: SignIn; label: string; hint: string }[] = [
  {
    value: 'team',
    label: 'Team account',
    hint: 'Every call signs in as one account the team connects.',
  },
  {
    value: 'person',
    label: 'Each person’s own account',
    hint: 'Calls act as the person who asked. Anyone who has not connected is asked.',
  },
  {
    value: 'person_or_team',
    label: 'Each person, team account as backup',
    hint: 'Runs with nobody behind them use the team account.',
  },
];

const message = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong');

/**
 * The one dialog that connects, edits and reconnects a system (c-580): the fields come from the system's sign-in kind
 * (`GET /v1/connection-kinds`), one section per environment, each saved and tested on its own before the connection is
 * called working; a sealed key reads as set and is replaced only by typing a new one. A new system that is cancelled
 * after a test made it is deleted. A kind whose `signsIn` is set ends with someone signing in, in a window of its own.
 */
export function ConnectSystemDialog({
  target,
  mode,
  environment,
  open,
  onOpenChange,
  onConnected,
}: {
  target: ConnectTarget;
  mode: ConnectMode;
  environment?: Environment;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConnected?: (c: ConnectionDetail) => void;
}) {
  const kinds = useConnectionKinds();
  const existingId = target.kind === 'connection' ? target.connectionId : null;
  const detail = useConnectionDetail(open ? existingId : null);
  const loading = kinds.isPending || (existingId != null && detail.isPending);
  const failed = kinds.isError ? kinds : detail.isError ? detail : null;

  const title = existingId
    ? (detail.data?.name ?? 'Connection')
    : target.kind === 'module'
      ? `Connect ${target.name}`
      : target.kind === 'plugin'
        ? `Connect ${target.card.name}`
        : 'Connect a system';
  const description =
    mode === 'edit'
      ? 'Change the keys for test or production. A saved key stays unless you type a new one.'
      : 'Enter the keys for test and production. Each is tested before it is called working.';
  if (failed || loading || !kinds.data) {
    return (
      <DialogShell open={open} onOpenChange={onOpenChange} size="lg" title={title} description={description} data-testid="connect-dialog">
        {failed ? (
          <QueryError what="what this system needs" error={failed.error} onRetry={() => void failed.refetch()} retrying={failed.isFetching} />
        ) : (
          <div className="flex flex-col gap-3" data-testid="connect-loading">
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        )}
      </DialogShell>
    );
  }
  if (target.kind === 'plugin') {
    return <PluginConnectForm open={open} card={target.card} kinds={kinds.data as Kinds} first={environment} onClose={() => onOpenChange(false)} />;
  }
  return (
    <ConnectForm
      // Keyed by the connection only: the dialog's own saves refetch it, and a remount would drop the form mid-test.
      key={existingId ?? target.kind}
      open={open}
      title={title}
      description={description}
      target={target}
      kinds={kinds.data as Kinds}
      detail={detail.data ?? null}
      first={environment}
      onClose={() => onOpenChange(false)}
      onConnected={onConnected}
    />
  );
}

function sectionsFor(kind: Kind, kinds: Kinds, detail: ConnectionDetail | null): Record<Environment, EnvDraft> {
  const groups = fieldsFor(kind, kinds);
  const saved = (env: Environment) => (detail?.environments as Record<string, SavedEnvironment> | undefined)?.[env] ?? null;
  return Object.fromEntries(kinds.environments.map((e) => [e.id, draftFor(e.id, groups, saved(e.id))]));
}

function ConnectForm({
  open,
  title,
  description,
  target,
  kinds,
  detail,
  first,
  onClose,
  onConnected,
}: {
  open: boolean;
  title: string;
  description: string;
  target: ConnectTarget;
  kinds: Kinds;
  detail: ConnectionDetail | null;
  first?: Environment;
  onClose: () => void;
  onConnected?: (c: ConnectionDetail) => void;
}) {
  const [name, setName] = React.useState(target.kind === 'module' ? target.name : '');
  const [category, setCategory] = React.useState('');
  const [kindId, setKindId] = React.useState(detail?.authKind ?? kinds.kinds.find((k) => k.id === 'api_key')?.id ?? kinds.kinds[0]?.id ?? 'none');
  const kind = kinds.kinds.find((k) => k.id === kindId) ?? kinds.kinds[0];
  const plan = planFor(kind);
  const groups = fieldsFor(kind, kinds);
  const [who, setWho] = React.useState<SignIn>((detail?.signIn as SignIn | undefined) ?? 'team');
  const [state, dispatch] = React.useReducer(reduce, initialState(sectionsFor(kind, kinds, detail), detail?.id ?? null));
  const revision = React.useRef(detail?.revision ?? 0);
  const latest = React.useRef<ConnectionDetail | null>(detail);
  const opened = React.useRef<Window | null>(null);

  const create = useCreateConnection();
  const bind = useBindModule();
  const setEnv = useSetEnvironment();
  const test = useTestEnvironment();
  const change = useChangeConnection();
  const remove = useDeleteConnection();
  const signIn = useStartSignIn();

  const keep = (c: ConnectionDetail) => {
    revision.current = c.revision;
    latest.current = c;
    return c;
  };

  const pickKind = (id: string) => {
    setKindId(id);
    const k = kinds.kinds.find((x) => x.id === id) ?? kind;
    dispatch({
      type: 'reset',
      sections: sectionsFor(k, kinds, null),
      connectionId: state.connectionId,
    });
  };

  React.useEffect(() => {
    const onMessage = (e: MessageEvent<ConnectedMessage>) => {
      if (e.origin !== window.location.origin || e.data?.type !== CONNECTED_MESSAGE || e.source !== opened.current) return;
      opened.current = null;
      dispatch({ type: 'signed-in' });
      toast.success(`${e.data.connection} is connected with the team account`);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  /** The connection to save into: the one open, or a new one made from the name and kind on the first save. */
  const ensure = async (): Promise<string> => {
    if (state.connectionId) return state.connectionId;
    const made = keep(
      await create.mutateAsync({
        name: name.trim(),
        authKind: kind.id,
        category: category.trim() || undefined,
        signIn: kind.perPerson ? who : 'team',
      }),
    );
    dispatch({ type: 'created', connectionId: made.id });
    if (target.kind === 'module')
      await bind.mutateAsync({
        moduleId: target.moduleId,
        connectionId: made.id,
      });
    return made.id;
  };

  const save = async (id: string, env: Environment) => {
    const draft = state.sections[env];
    if (draft.status !== 'dirty' && draft.status !== 'testing' && draft.status !== 'saving') return;
    const saved = keep(
      await setEnv.mutateAsync({
        connectionId: id,
        environment: env,
        body: environmentBody(draft, revision.current),
      }),
    );
    const secrets = (saved.environments as Record<string, SavedEnvironment>)[env]?.secrets ?? {};
    dispatch({
      type: 'saved',
      environment: env,
      secretSet: Object.fromEntries(Object.entries(secrets).map(([k, v]) => [k, Boolean((v as { set?: boolean })?.set)])),
    });
  };

  const runTest = async (env: Environment) => {
    if (state.busy) return;
    dispatch({ type: 'start', environment: env, status: 'testing' });
    try {
      const id = await ensure();
      await save(id, env);
      const tested = keep(await test.mutateAsync({ connectionId: id, environment: env }));
      dispatch({
        type: 'tested',
        environment: env,
        health: (tested.environments as Record<string, SavedEnvironment>)[env]?.health ?? tested.health ?? null,
      });
    } catch (e) {
      dispatch({ type: 'failed', environment: env, message: message(e) });
    }
  };

  const envs = ordered(kinds, first);
  const ready = envs.map((e) => e.id).filter((id) => complete(state.sections[id], groups));
  const canSave = plan.kind === 'none' || ready.length > 0;
  const named = Boolean(state.connectionId) || Boolean(name.trim());

  const finish = async () => {
    if (state.busy) return;
    const env = leading(kinds, ready) ?? envs[0].id;
    dispatch({ type: 'start', environment: env, status: 'saving' });
    try {
      const id = await ensure();
      for (const e of ready) await save(id, e);
      if (detail && kind.perPerson && who !== detail.signIn) {
        keep(
          await change.mutateAsync({
            path: { connection_id: id },
            body: {
              revision: revision.current,
              signIn: who,
              teamBackup: who === 'person_or_team',
            },
          }),
        );
      }
      if (plan.kind === 'account') {
        const start = await signIn.mutateAsync({
          connectionId: id,
          environment: env,
          account: 'team',
        });
        opened.current = openSignIn(start, id);
        dispatch({ type: 'signing-in' });
        return;
      }
      dispatch({ type: 'done' });
      toast.success(`${latest.current?.name ?? name} is saved`);
      if (latest.current) onConnected?.(latest.current);
      onClose();
    } catch (e) {
      dispatch({ type: 'failed', environment: env, message: message(e) });
    }
  };

  const cancel = async () => {
    if (state.created && state.connectionId) {
      try {
        if (target.kind === 'module')
          await bind.mutateAsync({
            moduleId: target.moduleId,
            connectionId: null,
          });
        await remove.mutateAsync(state.connectionId);
      } catch (e) {
        toast.error('Couldn’t remove the new connection', {
          description: message(e),
        });
      }
    }
    onClose();
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !o && void cancel()}
      size="lg"
      title={title}
      description={description}
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
            disabled={!named || !canSave || state.busy}
            data-testid="connect-submit"
          >
            {plan.kind === 'account' ? 'Save and connect the team account' : 'Save'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-5">
        {!detail && (
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="system-name" label="System name">
              <Input id="system-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Claims core" disabled={Boolean(state.connectionId)} />
            </FormField>
            <FormField id="system-kind" label="How it signs in">
              <Select value={kindId} onValueChange={pickKind} disabled={Boolean(state.connectionId)}>
                <SelectTrigger id="system-kind" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {kinds.kinds.map((k) => (
                    <SelectItem key={k.id} value={k.id}>
                      {k.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="system-category" label="Category" optional className="sm:col-span-2">
              <Input
                id="system-category"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="Core insurance"
                disabled={Boolean(state.connectionId)}
              />
            </FormField>
          </div>
        )}

        {kind.perPerson && (
          <RadioGroup
            value={who}
            onValueChange={(v) => setWho(v as SignIn)}
            className="grid gap-2 md:grid-cols-3"
            aria-label="Whose account calls use"
            data-testid="connect-who"
          >
            {WHO.map((o) => (
              <label
                key={o.value}
                htmlFor={`who-${o.value}`}
                className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', who === o.value && 'border-primary bg-primary/5')}
              >
                <RadioGroupItem value={o.value} id={`who-${o.value}`} className="mt-0.5" />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{o.label}</span>
                  <span className="block text-xs text-muted-foreground">{o.hint}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
        )}

        {plan.kind === 'none' ? (
          <p className="text-sm text-muted-foreground">{kind.label}: nothing to enter. Calls go to the system’s address with no sign-in.</p>
        ) : (
          envs.map(({ id: env, label }) => (
            <EnvSection
              key={env}
              env={env}
              label={label}
              draft={state.sections[env]}
              groups={groups}
              busy={state.busy}
              canTest={named && complete(state.sections[env], groups)}
              onSetting={(n, v) =>
                dispatch({
                  type: 'setting',
                  environment: env,
                  name: n,
                  value: v,
                })
              }
              onSecret={(n, v) =>
                dispatch({
                  type: 'secret',
                  environment: env,
                  name: n,
                  value: v,
                })
              }
              onTest={() => void runTest(env)}
            />
          ))
        )}

        {state.phase === 'signing-in' && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3" data-testid="connect-signing-in">
            <p className="text-sm">Finish signing in to {latest.current?.name ?? name} in the window that opened.</p>
            <Button type="button" size="sm" variant="outline" onClick={() => void finish()}>
              <ExternalLink />
              Reopen the window
            </Button>
          </div>
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
