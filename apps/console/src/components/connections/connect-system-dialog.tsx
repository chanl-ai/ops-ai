'use client';

import * as React from 'react';
import { ExternalLink } from 'lucide-react';
import { toast } from 'sonner';

import { useSignInWindow } from '@/components/connections/sign-in';
import { AccountFields } from '@/components/connections/account-fields';
import { PluginConnectForm } from '@/components/connections/plugin-connect-form';
import type { SignIn } from '@/components/connections/who-signs-in';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  type AccountDetail,
  type SystemCard,
  useAccountDetail,
  useAddAccount,
  useAddApp,
  useBindModule,
  useChangeAccount,
  useConnectionKinds,
  useDeleteAccount,
  useStartSignIn,
  useTestAccount,
} from '@/hooks/systems-queries';
import { accountBody, complete, draftFor, fieldsFor, initialState, planFor, reduce, type Kind, type Kinds, type SavedAccount } from '@/lib/connect-plan';
import type { ApiError } from '@/lib/api/contract';
import type { AccountRef } from '@/lib/types/connections';

/**
 * What the dialog connects: an account already there, a module's first app, a plugin's app, a new custom app, or a
 * custom app's sandbox account (`app` names it, its sign-in kind is the app's).
 */
export type ConnectTarget =
  | { kind: 'account'; account: AccountRef }
  | { kind: 'module'; moduleId: string; name: string }
  | { kind: 'plugin'; card: SystemCard; sandbox?: boolean }
  | { kind: 'new' }
  | { kind: 'sandbox'; appId: string; name: string; authKind: string };

export type ConnectMode = 'connect' | 'edit' | 'reconnect';

const message = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong');

/**
 * The one dialog that connects, edits and reconnects an app's account: the fields come from the app's sign-in kind
 * (`GET /v1/connection-kinds`), saved on the account and tested before it is called working; a sealed key reads as set
 * and is replaced only by typing a new one. An account made here and then cancelled is deleted. A kind whose `signsIn`
 * is set ends with someone signing in, in a window of its own.
 */
export function ConnectSystemDialog({
  target,
  mode,
  open,
  onOpenChange,
  onConnected,
}: {
  target: ConnectTarget;
  mode: ConnectMode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConnected?: (c: AccountDetail) => void;
}) {
  const kinds = useConnectionKinds();
  // A plugin's default account is read too, so its Edit starts from the settings saved on it; a new sandbox has none.
  const existing: AccountRef | null =
    target.kind === 'account'
      ? target.account
      : target.kind === 'plugin' && !target.sandbox && target.card.connectionId
        ? { appId: target.card.id, accountId: target.card.connectionId }
        : null;
  const detail = useAccountDetail(open ? existing : null);
  const loading = kinds.isPending || (existing != null && detail.isPending);
  const failed = kinds.isError ? kinds : detail.isError ? detail : null;

  // Who signs in is on the app page's Settings, so nothing here repeats it.
  const title = existing
    ? `${mode === 'reconnect' ? 'Reconnect' : 'Connect'} ${detail.data?.name ?? 'the app'}`
    : target.kind === 'module'
      ? `Connect ${target.name}`
      : target.kind === 'plugin'
        ? target.sandbox
          ? `Add a ${target.card.name} test account`
          : `Connect ${target.card.name}`
        : target.kind === 'sandbox'
          ? `Add a ${target.name} test account`
          : 'Add custom app';
  const description =
    mode === 'edit' ? 'A saved key stays unless you type a new one. It is tested before it is called working.' : 'It is tested before it is called working.';
  if (failed || loading || !kinds.data) {
    return (
      <DialogShell open={open} onOpenChange={onOpenChange} size="md" title={title} description={description} data-testid="connect-dialog">
        {failed ? (
          <QueryError what="what this app needs" error={failed.error} onRetry={() => void failed.refetch()} retrying={failed.isFetching} />
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
    return <PluginConnectForm open={open} card={target.card} sandbox={target.sandbox} kinds={kinds.data as Kinds} detail={detail.data ?? null} onClose={() => onOpenChange(false)} />;
  }
  return (
    <ConnectForm
      // Keyed by the account only: the dialog's own saves refetch it, and a remount would drop the form mid-test.
      key={existing?.accountId ?? target.kind}
      open={open}
      title={title}
      description={description}
      target={target}
      kinds={kinds.data as Kinds}
      detail={detail.data ?? null}
      onClose={() => onOpenChange(false)}
      onConnected={onConnected}
    />
  );
}

const draftOf = (kind: Kind, kinds: Kinds, detail: AccountDetail | null) => draftFor(fieldsFor(kind, kinds), (detail as SavedAccount | null) ?? null);

function ConnectForm({
  open,
  title,
  description,
  target,
  kinds,
  detail,
  onClose,
  onConnected,
}: {
  open: boolean;
  title: string;
  description: string;
  target: ConnectTarget;
  kinds: Kinds;
  detail: AccountDetail | null;
  onClose: () => void;
  onConnected?: (c: AccountDetail) => void;
}) {
  const sandbox = target.kind === 'sandbox';
  const [name, setName] = React.useState(target.kind === 'module' ? target.name : sandbox ? `${target.name} test account` : '');
  const [kindId, setKindId] = React.useState(
    detail?.authKind ?? (sandbox ? target.authKind : undefined) ?? kinds.kinds.find((k) => k.id === 'api_key')?.id ?? kinds.kinds[0]?.id ?? 'none',
  );
  const kind = kinds.kinds.find((k) => k.id === kindId) ?? kinds.kinds[0];
  const plan = planFor(kind);
  const groups = fieldsFor(kind, kinds);
  // Who signs in is set on the app page's Settings; a new app starts with the team account.
  const who: SignIn = (detail?.signIn as SignIn | undefined) ?? 'team';
  const [state, dispatch] = React.useReducer(reduce, initialState(draftOf(kind, kinds, detail), detail?.id ?? null, Boolean(detail)));
  const revision = React.useRef(detail?.revision ?? 0);
  const latest = React.useRef<AccountDetail | null>(detail);
  const opened = React.useRef(false);
  const connected = React.useRef(onConnected);
  const close = React.useRef(onClose);
  React.useEffect(() => {
    connected.current = onConnected;
    close.current = onClose;
  }, [onConnected, onClose]);

  const create = useAddApp();
  const add = useAddAccount();
  const bind = useBindModule();
  const test = useTestAccount();
  const change = useChangeAccount();
  const remove = useDeleteAccount();
  const signIn = useStartSignIn();

  /** The account the dialog writes to, once it has one. */
  const ref = (): AccountRef => ({ appId: target.kind === 'sandbox' ? target.appId : (latest.current?.appId ?? ''), accountId: state.connectionId ?? '' });

  const keep = (c: AccountDetail) => {
    revision.current = c.revision;
    latest.current = c;
    return c;
  };

  const pickKind = (id: string) => {
    setKindId(id);
    const k = kinds.kinds.find((x) => x.id === id) ?? kind;
    dispatch({ type: 'reset', draft: draftOf(k, kinds, null), connectionId: state.connectionId });
  };

  const signInWindow = useSignInWindow({
    onConnected: (m) => {
      if (!opened.current) return;
      opened.current = false;
      dispatch({ type: 'signed-in' });
      toast.success(`${m.connection} is connected with the team account`);
      // Save opened this window, so the account signing in is the last step: the dialog closes.
      dispatch({ type: 'done' });
      if (latest.current) connected.current?.(latest.current);
      close.current();
    },
    onFailed: (why) => {
      if (!opened.current) return;
      opened.current = false;
      dispatch({ type: 'failed', message: why });
    },
    onClosed: () => {
      if (!opened.current) return;
      opened.current = false;
      dispatch({ type: 'failed', message: 'The window was closed before access was allowed. Save again to try once more.' });
    },
  });

  /**
   * The account to save into: the one open, or one made on the first save, a new app's first account from the name
   * and kind, or a sandbox account of the app.
   */
  const ensure = async (): Promise<AccountRef> => {
    if (state.connectionId) return ref();
    const made = keep(
      target.kind === 'sandbox'
        ? await add.mutateAsync({ appId: target.appId, body: { name: name.trim(), sandbox: true } })
        : await create.mutateAsync({ name: name.trim(), authKind: kind.id, signIn: kind.perPerson ? who : 'team', sandbox: false }),
    );
    dispatch({ type: 'created', connectionId: made.id });
    if (target.kind === 'module')
      await bind.mutateAsync({
        moduleId: target.moduleId,
        connectionId: made.id,
      });
    // A sandbox belongs to the app the dialog was opened for; a new app's id is its first account's, as answered.
    return { appId: target.kind === 'sandbox' ? target.appId : made.appId, accountId: made.id };
  };

  const save = async (a: AccountRef) => {
    const draft = state.draft;
    if (draft.status !== 'dirty' && draft.status !== 'testing' && draft.status !== 'saving') return;
    const saved = keep(await change.mutateAsync({ ...a, body: accountBody(draft, revision.current) }));
    dispatch({
      type: 'saved',
      secretSet: Object.fromEntries(Object.entries(saved.secrets).map(([k, v]) => [k, Boolean((v as { set?: boolean })?.set)])),
    });
  };

  // The field a refused test or save named, so it is shown where it is, never left hidden under More settings.
  const [missing, setMissing] = React.useState<{ name: string; message: string } | null>(null);
  const fieldOf = (e: unknown) => {
    const err = e as ApiError;
    const named = typeof err?.details?.field === 'string' ? err.details.field : err?.code === 'test_path_missing' ? 'testPath' : null;
    return named ? { name: named, message: message(e) } : null;
  };

  const runTest = async () => {
    if (state.busy) return;
    setMissing(null);
    dispatch({ type: 'start', status: 'testing' });
    try {
      const a = await ensure();
      await save(a);
      const tested = keep(await test.mutateAsync(a));
      dispatch({ type: 'tested', health: tested.health ?? null });
    } catch (e) {
      setMissing(fieldOf(e));
      dispatch({ type: 'failed', message: message(e) });
    }
  };

  const ready = complete(state.draft, groups);
  const canSave = plan.kind === 'none' || ready;
  const named = Boolean(state.connectionId) || Boolean(name.trim());

  const finish = async () => {
    if (state.busy) return;
    // A sign-in window opens in the click, before any call, so a pop-up blocker lets it through.
    const signsInNow = plan.kind === 'account' && !state.signedIn;
    const w = signsInNow ? signInWindow.open(latest.current?.name ?? name) : null;
    if (signsInNow && !w) return;
    dispatch({ type: 'start', status: 'saving' });
    try {
      const a = await ensure();
      if (ready) await save(a);
      if (detail && kind.perPerson && who !== detail.signIn) {
        keep(await change.mutateAsync({ ...a, body: { revision: revision.current, signIn: who, teamBackup: who === 'person_or_team' } }));
      }
      if (w) {
        const begin = async () => {
          const start = await signIn.mutateAsync({ ...a, account: 'team' });
          opened.current = true;
          w.go(start, a);
          dispatch({ type: 'signing-in' });
        };
        // Try again in the window starts the same sign-in again, on the account already saved.
        w.retry(() =>
          void begin().catch((e: unknown) => {
            w.fail(message(e));
            dispatch({ type: 'failed', message: message(e) });
          }),
        );
        await begin();
        return;
      }
      dispatch({ type: 'done' });
      toast.success(`${latest.current?.name ?? name} is saved`);
      if (latest.current) onConnected?.(latest.current);
      onClose();
    } catch (e) {
      w?.fail(message(e));
      dispatch({ type: 'failed', message: message(e) });
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
        await remove.mutateAsync(ref());
      } catch (e) {
        toast.error(sandbox ? 'Couldn’t remove the new test account' : 'Couldn’t remove the new app', {
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
      size="md"
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
            isLoading={state.busy && state.draft.status !== 'testing'}
            disabled={!named || !canSave || state.busy}
            data-testid="connect-submit"
          >
            {plan.kind === 'account' ? 'Connect' : 'Save'}
          </LoadingButton>
        </>
      }
    >
      <div className="flex min-w-0 flex-col gap-5">
        {!detail && (
          <div className="grid gap-4">
            <FormField id="system-name" label={sandbox ? 'Account name' : 'App name'}>
              <Input id="system-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Claims core" disabled={Boolean(state.connectionId)} />
            </FormField>
            {/* A sandbox account signs in the way its app does. */}
            {!sandbox && (
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
            )}
          </div>
        )}

        {plan.kind === 'none' ? (
          <p className="text-sm text-muted-foreground">{kind.label}: nothing to enter. Calls go to the app’s address with no sign-in.</p>
        ) : (
          <AccountFields
            draft={state.draft}
            groups={groups}
            busy={state.busy}
            canTest={named && ready}
            onSetting={(n, v) => dispatch({ type: 'setting', name: n, value: v })}
            onSecret={(n, v) => dispatch({ type: 'secret', name: n, value: v })}
            onTest={() => void runTest()}
            missing={missing}
          />
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
