'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { MoreVertical, Plug, UserRound } from 'lucide-react';
import { toast } from 'sonner';

import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { OwnCredentialsForm } from '@/components/connections/own-credentials-form';
import { useSignInWindow } from '@/components/connections/sign-in';
import { DialogShell } from '@/components/shared/dialog-shell';
import { useConnectionKinds, useDisconnect, useMyConnections, useRefreshMine, useStartSignIn } from '@/hooks/connections-queries';
import { useTestAccount } from '@/hooks/systems-queries';
import { facetFilterFn } from '@/hooks/use-list-params';
import { useTeam } from '@/hooks/use-team';
import { shortDate } from '@/lib/format';
import type { MyConnection } from '@/lib/types/connections';

/** What a key, password or token kind asks for, named by its last secret field ("key", "password", "token"). */
function useNoun(c: MyConnection): string {
  const kinds = useConnectionKinds();
  const fields = kinds.data?.find((k) => k.id === c.authKind)?.fields ?? [];
  const secret = [...c.personFields].reverse().find((n) => fields.find((f) => f.name === n)?.secret);
  return (fields.find((f) => f.name === secret)?.label ?? c.personFields.at(-1) ?? 'key').toLowerCase();
}

/**
 * An OAuth account the person has not connected: their own sign-in opens in a window, as from the chat. Starting it
 * needs the account's app, so the button waits for a row that names it.
 */
function ConnectButton({ c, label = 'Connect' }: { c: MyConnection; label?: string }) {
  const start = useStartSignIn();
  const refresh = useRefreshMine();
  const signIn = useSignInWindow({
    onConnected: () => (toast.success(`${c.connection} is connected`), refresh()),
    onFailed: (why) => toast.error(`Couldn’t connect ${c.connection}`, { description: why }),
  });
  return (
    <Button
      size="sm"
      onClick={() => {
        // Opened in the click, before the call that starts the sign-in, so a pop-up blocker lets it through.
        if (!c.appId) return;
        const account = { appId: c.appId, accountId: c.connectionId };
        const w = signIn.open(c.connection);
        if (!w) return;
        start.mutate({ ...account, account: 'self' }, { onSuccess: (s) => w.go(s, account), onError: (e) => w.fail(e.message) });
      }}
      disabled={start.isPending || !c.appId}
      data-testid={`connect-${c.connectionId}`}
    >
      {label}
    </Button>
  );
}

/** One row's line under its state: whom it is connected as and since when, or why it ended; never part of a secret. */
function describe(c: MyConnection): string {
  if (c.refused) {
    const when = c.refusedAt ? ` ${shortDate(c.refusedAt)}` : '';
    return [c.personFields.length ? `Refused${when}` : `Sign-in expired${when}`, c.refusedReason].filter(Boolean).join(' · ');
  }
  // Signed in, but the test call after it failed: the account stays connected and says why.
  if (c.test?.status === 'failed') return `Signed in, but a test call failed: ${c.test.message || 'no reason given'}`;
  const since = c.since ? `since ${shortDate(c.since)}` : null;
  return [c.authConfig ? `Through ${c.authConfig}` : c.method, since].filter(Boolean).join(' · ');
}

/** The row's state, in the words the Accounts tab uses. */
const STATE_LABEL = { connected: 'Connected', expired: 'Expired', not_connected: 'Not connected' } as const;

/** The row's one action by its state: Connect or Add key while not connected, Reconnect once expired. */
function MainAction({ c, onGive }: { c: MyConnection; onGive: () => void }) {
  const noun = useNoun(c);
  const keyed = c.personFields.length > 0;
  const state = c.state ?? (c.connected ? 'connected' : 'not_connected');
  if (state === 'not_connected')
    return keyed ? (
      <Button size="sm" onClick={onGive} data-testid={`add-own-${c.connectionId}`}>
        Add {noun}
      </Button>
    ) : (
      <ConnectButton c={c} />
    );
  if (state === 'expired' || c.test?.status === 'failed')
    return keyed ? (
      <Button size="sm" onClick={onGive} data-testid={`replace-own-${c.connectionId}`}>
        Replace {noun}
      </Button>
    ) : (
      <ConnectButton c={c} label="Reconnect" />
    );
  return null;
}

/** A connected row's menu: Test now, Replace the key, Disconnect. */
function RowMenu({ c, onEnd, onGive }: { c: MyConnection; onEnd: () => void; onGive: () => void }) {
  const noun = useNoun(c);
  const test = useTestAccount();
  if ((c.state ?? (c.connected ? 'connected' : 'not_connected')) === 'not_connected' || !c.appId) return null;
  const appId = c.appId;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`${c.app} actions`} data-testid={`my-account-menu-${c.connectionId}`}>
          <MoreVertical />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onClick={() =>
            test.mutate(
              { appId, accountId: c.connectionId, account: 'self' },
              {
                onSuccess: (r) => (r.health?.status === 'ok' ? toast.success(`${c.app} works`) : toast.error(`${c.app}’s test failed`, { description: r.health?.message ?? undefined })),
                onError: (e) => toast.error('Couldn’t test it', { description: e.message }),
              },
            )
          }
        >
          Test now
        </DropdownMenuItem>
        {c.personFields.length > 0 && <DropdownMenuItem onClick={onGive}>Replace {noun}</DropdownMenuItem>}
        <DropdownMenuItem onClick={onEnd} className="text-destructive-text" data-testid={`disconnect-${c.connectionId}`}>
          Disconnect
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * My accounts (in the sidebar's top rows): every app in the team the person may sign in to with their own account,
 * one row each with whom they are signed in as and its state, and Connect or Reconnect. The list, each state and the
 * auth config come joined from the service.
 */
function MyAccountsPage() {
  const { team } = useTeam();
  const mine = useMyConnections(true);
  const disconnect = useDisconnect();
  const [ending, setEnding] = React.useState<MyConnection | null>(null);
  const [giving, setGiving] = React.useState<MyConnection | null>(null);
  const columns: ColumnDef<MyConnection>[] = [
    {
      accessorKey: 'app',
      header: ({ column }) => <DataTableColumnHeader column={column} title="App" />,
      meta: { kind: 'name' },
      cell: ({ row: { original: c } }) => (
        <span className="flex min-w-0 items-center gap-3" data-testid={`my-account-${c.connectionId}`}>
          <Avatar className="size-8 rounded-md">
            {c.logo && <AvatarImage src={c.logo} alt="" />}
            <AvatarFallback className="rounded-md text-xs font-semibold">{c.app.slice(0, 2).toUpperCase()}</AvatarFallback>
          </Avatar>
          <span className="flex min-w-0 flex-col">
            <span className="flex flex-wrap items-center gap-2">
              <span className="truncate">{c.app}</span>
              {c.sandbox && <Badge variant="outline">Test</Badge>}
            </span>
            {c.app !== c.connection && <span className="truncate text-xs text-muted-foreground">{c.connection}</span>}
          </span>
        </span>
      ),
    },
    {
      id: 'account',
      accessorFn: (c) => c.account ?? '',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Signed in as" />,
      // Who the system says signed in. A connected account whose system has not said yet (no id token, no test since)
      // reads so, apart from one never connected; its next test names it.
      cell: ({ row: { original: c } }) =>
        c.account ? (
          <span className="text-sm">{c.account}</span>
        ) : (c.state ?? (c.connected ? 'connected' : 'not_connected')) === 'not_connected' ? (
          <span className="text-sm text-muted-foreground">—</span>
        ) : (
          <span className="text-sm text-muted-foreground" title="Test now asks the app who signed in" data-testid={`my-account-unnamed-${c.connectionId}`}>
            Not named yet
          </span>
        ),
    },
    {
      id: 'state',
      accessorFn: (c) => STATE_LABEL[c.state ?? (c.connected ? 'connected' : 'not_connected')],
      header: ({ column }) => <DataTableColumnHeader column={column} title="State" />,
      meta: { kind: 'status' },
      cell: ({ row: { original: c } }) => {
        const state = c.state ?? (c.connected ? 'connected' : 'not_connected');
        return (
          <span className="flex flex-col gap-1">
            <span className="flex flex-wrap items-center gap-2">
              <Badge variant={state === 'connected' ? 'secondary' : state === 'expired' ? 'destructive' : 'outline'} data-testid={`my-account-state-${c.connectionId}`}>
                {STATE_LABEL[state]}
              </Badge>
              <MainAction c={c} onGive={() => setGiving(c)} />
            </span>
            {state !== 'not_connected' && <span className="text-xs text-muted-foreground">{describe(c)}</span>}
          </span>
        );
      },
      filterFn: facetFilterFn,
    },
    {
      id: 'actions',
      enableHiding: false,
      cell: ({ row: { original: c } }) => (
        <StopRowClick>
          <RowMenu c={c} onEnd={() => setEnding(c)} onGive={() => setGiving(c)} />
        </StopRowClick>
      ),
    },
  ];

  const body = mine.isPending ? (
    <PageSkeleton statCards={0} tableRows={4} />
  ) : mine.isError ? (
    <QueryError what="your accounts" onRetry={() => void mine.refetch()} retrying={mine.isFetching} error={mine.error} testId="my-connections-error" />
  ) : (
    <div data-testid="my-connections">
      <DataTableWithViews
        columns={columns}
        data={mine.data ?? []}
        getRowId={(c) => c.connectionId}
        searchColumn="app"
        searchPlaceholder="Search apps…"
        hideViewSwitcher
        filters={[{ column: 'state', title: 'State', options: Object.values(STATE_LABEL).map((v) => ({ label: v, value: v })) }]}
        emptyState={
          <EmptyState icon={Plug} title="No app to sign in to yet" description="Apps your team adds that allow personal accounts show here." testId="my-connections-empty" />
        }
      />
    </div>
  );

  return (
    <PageLayout
      icon={UserRound}
      title="My accounts"
      description={`Apps in ${team?.name ?? 'this team'} you can sign in to with your own account. Tools you run, and agents acting for you, use them.`}
    >
      {body}
      <DialogShell
        open={giving !== null}
        onOpenChange={(open) => !open && setGiving(null)}
        size="sm"
        title={giving ? `${giving.connected ? 'Replace' : 'Add'} your ${giving.connection} ${giving.method}` : ''}
        description={giving ? `${giving.connection} lets each person use their own ${giving.method}. Only your requests use it.` : undefined}
      >
        {giving && (
          <OwnCredentialsForm
            connectionId={giving.connectionId}
            connection={giving.connection}
            authKind={giving.authKind}
            personFields={giving.personFields}
            docsUrl={giving.docsUrl}
            submitLabel={`Save ${giving.method}`}
            cancelLabel="Cancel"
            onCancel={() => setGiving(null)}
            onDone={() => {
              toast.success(`Saved for ${giving.connection}`);
              setGiving(null);
            }}
          />
        )}
      </DialogShell>
      <DeleteDialog
        open={ending !== null}
        onOpenChange={(open) => !open && setEnding(null)}
        entityType="app"
        entityName={ending?.connection}
        verb="Disconnect"
        testIdPrefix="my-connection"
        description={`Your tools and agents lose access to ${ending?.connection ?? 'this app'} as you until you reconnect it. The team account stays.`}
        isLoading={disconnect.isPending}
        onConfirm={async () => {
          if (!ending) return;
          await disconnect.mutateAsync(ending.connectionId);
          toast.success(`Disconnected from ${ending.connection}`);
          setEnding(null);
        }}
      />
    </PageLayout>
  );
}

export default function Page() {
  return <MyAccountsPage />;
}
