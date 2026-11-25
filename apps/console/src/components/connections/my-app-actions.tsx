'use client';

import * as React from 'react';
import Link from 'next/link';
import { MoreVertical } from 'lucide-react';
import { toast } from 'sonner';

import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { AddAuthConfigButton } from '@/components/connections/app-actions';
import { AnotherAccountDialog, type AnotherAccount } from '@/components/connections/another-account-dialog';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { OwnCredentialsForm } from '@/components/connections/own-credentials-form';
import { useSignInWindow } from '@/components/connections/sign-in';
import { type MyConnector, useAddOwnAccount, useDisconnect, useRefreshMine, useStartSignIn } from '@/hooks/connections-queries';
import { useTestAccount } from '@/hooks/systems-queries';
import { appPageHref } from '@/lib/app-links';
import { appStateFor } from '@/lib/app-state';

/** Where a row names its account but the person has none connected, so no row shows a bare dash. */
export const NO_ACCOUNT = 'No account connected';

/** The person's own sign-in on the row's account ended, so it reads Sign in again rather than Connect. */
export const signInEnded = (c: MyConnector) => c.accounts.find((a) => a.connectionId === c.primaryAccountId)?.state === 'expired';

/** Whether chat uses it, as the app's In chat line says it. */
export function inChatWords(c: MyConnector): string {
  if (c.appGroup === 'on') return 'On in chat';
  if (c.appGroup === 'needs_you') return signInEnded(c) ? 'Paused until you sign in' : 'Asks when a tool needs it';
  return c.mayManage ? 'Your team sets it up first' : 'An admin sets it up first';
}

/** What a person with no admin rights reads on an app the team has not set up: one plain line, naming who can. */
export const NOT_SET_UP = 'Not set up for your team yet';

export interface MyAppControls {
  /** Starts the person's own sign-in on the app, or opens the key form for a key kind. */
  connect: (c: MyConnector) => void;
  /** An attempt is under way. */
  pending: boolean;
  /** The reason the app's last sign-in attempt in this window failed, by app id; cleared by the next attempt. */
  failed: Readonly<Record<string, string>>;
  disconnect: (c: MyConnector) => void;
  another: (c: MyConnector) => void;
}

/**
 * The person's sign-in actions for My apps, shared by the list and an app's page: the sign-in window as from the chat
 * (opened in the click, so a pop-up blocker lets it through), the key form for a key kind, Add another account and
 * Disconnect, with their dialogs. A refused sign-in is kept per app, so its card says Couldn’t connect and why.
 */
export function MyAppActions({ children, onDisconnected }: { children: (controls: MyAppControls) => React.ReactNode; onDisconnected?: () => void }) {
  const start = useStartSignIn();
  const addAccount = useAddOwnAccount();
  const refresh = useRefreshMine();
  const remove = useDisconnect();
  const lastApp = React.useRef<string | null>(null);
  const [failed, setFailed] = React.useState<Record<string, string>>({});
  const [giving, setGiving] = React.useState<{ c: MyConnector; accountId: string } | null>(null);
  const [adding, setAdding] = React.useState<{ c: MyConnector; error: string | null } | null>(null);
  const [ending, setEnding] = React.useState<MyConnector | null>(null);

  const clear = (appId: string) => setFailed(({ [appId]: _gone, ...rest }) => rest);
  const fail = (why: string, appId = lastApp.current) => {
    if (appId) setFailed((f) => ({ ...f, [appId]: why }));
    toast.error('Couldn’t connect', { description: why });
  };
  const signIn = useSignInWindow({
    onConnected: () => (lastApp.current && clear(lastApp.current), toast.success('Connected'), refresh()),
    onFailed: (why) => fail(why),
  });

  const go = (c: MyConnector) => {
    const target = c.accounts.find((a) => a.connectionId === c.primaryAccountId);
    if (!target) return;
    lastApp.current = c.appId;
    clear(c.appId);
    if ((c.personFields ?? []).length > 0) return setGiving({ c, accountId: target.connectionId });
    const account = { appId: c.appId, accountId: target.connectionId };
    const w = signIn.open(c.name);
    if (!w) return;
    start.mutate({ ...account, account: 'self' }, { onSuccess: (s) => w.go(s, account), onError: (e) => (w.fail(e.message), fail(e.message, c.appId)) });
  };

  const addAnother = (c: MyConnector, a: AnotherAccount, onError: (why: string) => void) => {
    if (!c.primaryAccountId) return;
    lastApp.current = c.appId;
    const w = signIn.open(c.name);
    if (!w) return;
    addAccount.mutate(
      { accountId: c.primaryAccountId, ...a },
      {
        onSuccess: (s) => w.go(s, { appId: c.appId, accountId: s.connectionId ?? c.primaryAccountId ?? '' }),
        onError: (e) => (w.fail(e.message), onError(e.message)),
      },
    );
  };

  return (
    <>
      {children({ connect: go, pending: start.isPending || addAccount.isPending, failed, disconnect: setEnding, another: (c) => setAdding({ c, error: null }) })}
      {adding && (
        <AnotherAccountDialog
          connector={adding.c}
          busy={addAccount.isPending}
          error={adding.error}
          onClose={() => setAdding(null)}
          onAdd={(a) => addAnother(adding.c, a, (why) => setAdding({ c: adding.c, error: why }))}
        />
      )}
      <DialogShell
        open={giving !== null}
        onOpenChange={(o) => !o && setGiving(null)}
        size="sm"
        title={giving ? `Add your ${giving.c.name} ${giving.c.method ?? 'key'}` : ''}
        description={giving ? `${giving.c.name} lets each person use their own ${giving.c.method ?? 'key'}. Only your requests use it.` : undefined}
      >
        {giving && (
          <OwnCredentialsForm
            connectionId={giving.accountId}
            connection={giving.c.name}
            authKind={giving.c.authKind ?? undefined}
            personFields={giving.c.personFields ?? []}
            docsUrl={giving.c.docsUrl}
            submitLabel={`Save ${giving.c.method ?? 'key'}`}
            cancelLabel="Cancel"
            onCancel={() => setGiving(null)}
            onDone={() => {
              toast.success(`Saved for ${giving.c.name}`);
              setGiving(null);
            }}
          />
        )}
      </DialogShell>
      <DeleteDialog
        open={ending !== null}
        onOpenChange={(o) => !o && setEnding(null)}
        entityType="app"
        entityName={ending?.name}
        verb="Disconnect"
        testIdPrefix="my-connection"
        description={`Chat and agents working for you lose ${ending?.name ?? 'this app'} as you until you connect it again. The team login does not act for you; it serves only runs nobody started.`}
        isLoading={remove.isPending}
        onConfirm={async () => {
          if (!ending?.primaryAccountId) return;
          await remove.mutateAsync(ending.primaryAccountId);
          toast.success(`Disconnected from ${ending.name}`);
          setEnding(null);
          onDisconnected?.();
        }}
      />
    </>
  );
}

/**
 * The app's one action for the person. Where the person's own sign-in is the next step it is always Connect (Sign in
 * again, Add key), whoever they are in the team. Where the team has not set the app up, an admin is offered the setup
 * on the spot and anyone else reads who can do it; a connected app has none (its menu is `MyAppMenu`).
 */
export function MyAppAction({ c, controls }: { c: MyConnector; controls: MyAppControls }) {
  if (c.appGroup === 'needs_you')
    return (
      <Button size="sm" onClick={() => controls.connect(c)} disabled={controls.pending} data-testid={`connector-action-${c.appId}`}>
        {signInEnded(c) ? 'Sign in again' : (c.personFields ?? []).length > 0 ? 'Add key' : 'Connect'}
      </Button>
    );
  if (c.appGroup !== 'needs_admin') return null;
  if (!c.mayManage) return <AskAnAdmin testId={`connector-ask-${c.appId}`} />;
  const { action } = appStateFor(c.appState, c.appGroup, true);
  if (action === 'add_auth_config') return <AddAuthConfigButton appId={c.appId} testId={`connector-add-auth-config-${c.appId}`} />;
  const fix = action === 'fix_auth_config';
  return (
    <Button size="sm" variant="outline" asChild data-testid={`connector-${fix ? 'fix-auth-config' : 'turn-on'}-${c.appId}`}>
      <Link href={appPageHref(c.appId, fix ? 'auth' : undefined)}>{fix ? 'Fix setup' : 'Turn on'}</Link>
    </Button>
  );
}

/** Test now, Add another account and Disconnect, on a connected app. */
export function MyAppMenu({ c, controls }: { c: MyConnector; controls: MyAppControls }) {
  const test = useTestAccount();
  if (c.appGroup !== 'on' || !c.primaryAccountId) return null;
  const accountId = c.primaryAccountId;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`${c.name} actions`} data-testid={`connector-menu-${c.appId}`}>
          <MoreVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onClick={() =>
            test.mutate(
              { appId: c.appId, accountId, account: 'self' },
              {
                onSuccess: (r) => (r.health?.status === 'ok' ? toast.success(`${c.name} works`) : toast.error(`${c.name}’s test failed`, { description: r.health?.message ?? undefined })),
                onError: (e) => toast.error('Couldn’t test it', { description: e.message }),
              },
            )
          }
        >
          Test now
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => controls.another(c)} data-testid={`connector-another-${c.appId}`}>
          Add account
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => controls.disconnect(c)} className="text-destructive-text" data-testid={`connector-disconnect-${c.appId}`}>
          Disconnect
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The card's own line for a sign-in the app refused, with its reason; nothing until one fails. */
export function CouldntConnect({ appId, why }: { appId: string; why?: string }) {
  if (!why) return null;
  return (
    <p className="text-sm text-destructive-text" role="alert" data-testid={`connector-failed-${appId}`}>
      Couldn’t connect · {why}
    </p>
  );
}
