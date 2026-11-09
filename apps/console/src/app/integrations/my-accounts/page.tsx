'use client';

import * as React from 'react';
import Link from 'next/link';
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
import { APP_CARD_GRID, AppCard } from '@/components/connections/app-card';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { ConnectorSheet, NO_ACCOUNT, NOT_SET_UP, inChatWords, signInEnded } from '@/components/connections/connector-sheet';
import { AddAuthConfigButton } from '@/components/connections/app-actions';
import { AppStateBadge } from '@/components/connections/app-state-badge';
import { APP_STATES, appStateFor } from '@/lib/app-state';
import { OwnCredentialsForm } from '@/components/connections/own-credentials-form';
import { useSignInWindow } from '@/components/connections/sign-in';
import { DialogShell } from '@/components/shared/dialog-shell';
import { type MyConnector, useAddOwnAccount, useDisconnect, useMyConnectors, useRefreshMine, useStartSignIn } from '@/hooks/connections-queries';
import { useTestAccount } from '@/hooks/systems-queries';
import { facetFilterFn } from '@/hooks/use-list-params';
import { useTeam } from '@/hooks/use-team';
import { plural, shortDate } from '@/lib/format';
import { appPageHref } from '@/lib/app-links';
import { MY_CONNECTORS } from '@/lib/nav';

/**
 * The person's own sign-in at the system, in a window as from the chat; a key kind opens the key form instead. The
 * window opens in the click, before the call that starts the sign-in, so a pop-up blocker lets it through.
 */
function useConnect(onKey: (c: MyConnector, accountId: string) => void) {
  const start = useStartSignIn();
  const another = useAddOwnAccount();
  const refresh = useRefreshMine();
  const signIn = useSignInWindow({
    onConnected: () => (toast.success('Connected'), refresh()),
    onFailed: (why) => toast.error('Couldn’t connect', { description: why }),
  });
  return {
    pending: start.isPending || another.isPending,
    go: (c: MyConnector, more = false) => {
      if (more) {
        // Another account of the person's own, through the same auth config as the one they use.
        if (!c.primaryAccountId) return;
        const w = signIn.open(c.name);
        if (!w) return;
        another.mutate(c.primaryAccountId, {
          onSuccess: (s) => w.go(s, { appId: c.appId, accountId: s.connectionId ?? c.primaryAccountId ?? '' }),
          onError: (e) => w.fail(e.message),
        });
        return;
      }
      const target = c.accounts.find((a) => a.connectionId === c.primaryAccountId);
      if (!target) return;
      if ((c.personFields ?? []).length > 0) return onKey(c, target.connectionId);
      const account = { appId: c.appId, accountId: target.connectionId };
      const w = signIn.open(c.name);
      if (!w) return;
      start.mutate({ ...account, account: 'self' }, { onSuccess: (s) => w.go(s, account), onError: (e) => w.fail(e.message) });
    },
  };
}

/** The row's one action, from its app's state (lib/app-state.ts): Connect, Add key or Sign in again, Turn on, Add an
 * auth config or the admins to ask; none once it acts as the person. */
function RowAction({ c, connect }: { c: MyConnector; connect: ReturnType<typeof useConnect> }) {
  const { action } = appStateFor(c.appState, c.appGroup, c.mayManage);
  if (action === 'turn_on')
    return (
      <Button size="sm" variant="outline" asChild data-testid={`connector-turn-on-${c.appId}`}>
        <Link href={appPageHref(c.appId)}>Turn on</Link>
      </Button>
    );
  if (action === 'add_auth_config') return <AddAuthConfigButton appId={c.appId} testId={`connector-add-auth-config-${c.appId}`} />;
  if (action === 'fix_auth_config')
    return (
      <Button size="sm" variant="outline" asChild data-testid={`connector-fix-auth-config-${c.appId}`}>
        <Link href={appPageHref(c.appId, 'auth')}>Fix the auth config</Link>
      </Button>
    );
  if (action === 'ask_admin') return <AskAnAdmin testId={`connector-ask-${c.appId}`} lead={`${NOT_SET_UP}.`} />;
  if (c.appGroup !== 'needs_you') return null;
  const keyed = (c.personFields ?? []).length > 0;
  return (
    <Button size="sm" onClick={() => connect.go(c)} disabled={connect.pending} data-testid={`connector-action-${c.appId}`}>
      {signInEnded(c) ? 'Sign in again' : keyed ? 'Add key' : 'Connect'}
    </Button>
  );
}

/** A connected row's menu: Test now, Add another account, Disconnect. */
function RowMenu({ c, onEnd, onAnother }: { c: MyConnector; onEnd: () => void; onAnother: () => void }) {
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
        <DropdownMenuItem onClick={onAnother} data-testid={`connector-another-${c.appId}`}>
          Add another account
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onEnd} className="text-destructive-text" data-testid={`connector-disconnect-${c.appId}`}>
          Disconnect
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/**
 * One connector as a card, as Team setup draws an app: logo and name, what it can do as the person, whom it signs in
 * as, its state and its one action (Connect, Sign in again, Turn on or the admins to ask; the menu once connected).
 * The card opens its details; on a phone the cards stack, so the action stays on screen.
 */
function ConnectorCard({ c, connect, onOpen, onEnd, onAnother }: { c: MyConnector; connect: ReturnType<typeof useConnect>; onOpen: () => void; onEnd: () => void; onAnother: () => void }) {
  return (
    <AppCard
      testId={`connector-${c.appId}`}
      state={c.appState}
      name={c.name}
      logo={c.logo}
      onOpen={onOpen}
      linkTestId={`connector-open-${c.appId}`}
      footState={
        <AppStateBadge card={c} testId={`connector-state-${c.appId}`} />
      }
      action={c.appGroup === 'on' ? <RowMenu c={c} onEnd={onEnd} onAnother={onAnother} /> : <RowAction c={c} connect={connect} />}
    >
      <p className="text-sm text-muted-foreground" data-testid={`connector-can-do-${c.appId}`}>
        {c.canDo}
      </p>
      <div className="text-sm" data-testid={`connector-signed-in-${c.appId}`}>
        <SignedInAs c={c} />
      </div>
      <p className="text-xs text-muted-foreground">{c.appGroup === 'on' && c.since ? `${inChatWords(c)} · since ${shortDate(c.since)}` : inChatWords(c)}</p>
    </AppCard>
  );
}

/** Whom it signs in as: the primary account, with the other connected ones as a count. */
function SignedInAs({ c }: { c: MyConnector }) {
  if (c.appGroup === 'needs_admin' || (c.appGroup === 'needs_you' && !signInEnded(c)))
    return (
      <span className="text-sm text-muted-foreground" data-testid={`connector-missing-${c.appId}`}>
        {NO_ACCOUNT}
      </span>
    );
  const more = c.accountCount - 1;
  return (
    <span className="flex flex-wrap items-center gap-2 text-sm">
      <span className="truncate">{signInEnded(c) ? `Was ${c.account ?? 'your account'}` : (c.account ?? 'Your account')}</span>
      {more > 0 && (
        <Badge variant="outline" data-testid={`connector-more-${c.appId}`}>
          +{plural(more, 'account')}
        </Badge>
      )}
    </span>
  );
}

/**
 * Connectors, Mine (the sidebar's top row): one row per app that acts as the person, with what it can do as them,
 * whom it signs in as, its state, whether chat uses it and its one action. Rows, states and counts come joined from
 * tools-service (GET /v1/me/connections). On a phone the state and action join the connector's cell.
 */
function ConnectorsPage() {
  const { team } = useTeam();
  const mine = useMyConnectors();
  const disconnect = useDisconnect();
  const [ending, setEnding] = React.useState<MyConnector | null>(null);
  const [giving, setGiving] = React.useState<{ c: MyConnector; accountId: string } | null>(null);
  const [open, setOpen] = React.useState<string | null>(null);
  const connect = useConnect((c, accountId) => setGiving({ c, accountId }));
  const shown = (mine.data ?? []).find((c) => c.appId === open) ?? null;
  const rows = React.useMemo(() => (mine.data ?? []).map((c) => ({ ...c, onRowClick: () => setOpen(c.appId) })), [mine.data]);
  // The cards are the list; the columns name what search and the State filter read.
  const columns: ColumnDef<MyConnector>[] = [
    { accessorKey: 'name', header: ({ column }) => <DataTableColumnHeader column={column} title="Connector" />, meta: { kind: 'name' } },
    { id: 'state', accessorFn: (c) => APP_STATES[c.appState].label, header: ({ column }) => <DataTableColumnHeader column={column} title="State" />, filterFn: facetFilterFn },
  ];
  const connected = (mine.data ?? []).filter((c) => c.appGroup === 'on').length;

  const body = mine.isPending ? (
    <PageSkeleton statCards={0} tableRows={4} />
  ) : mine.isError ? (
    <QueryError what="your connectors" onRetry={() => void mine.refetch()} retrying={mine.isFetching} error={mine.error} testId="connectors-error" />
  ) : (
    <div className="flex flex-col gap-2" data-testid="connectors">
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(c) => c.appId}
        defaultView="grid"
        gridClassName={APP_CARD_GRID}
        renderGridItem={(c) => (
          <ConnectorCard c={c} connect={connect} onOpen={() => setOpen(c.appId)} onEnd={() => setEnding(c)} onAnother={() => connect.go(c, true)} />
        )}
        searchColumn="name"
        searchPlaceholder="Search connectors…"
        hidePaginationOnOnePage
        rowNoun="connector"
        hideViewSwitcher
        filters={[{ column: 'state', title: 'State', options: [...new Set((mine.data ?? []).map((c) => APP_STATES[c.appState].label))].map((v) => ({ label: v, value: v })) }]}
        emptyState={
          <EmptyState
            icon={Plug}
            title="No connector needs your sign-in yet"
            description="Apps your team turns on that act as each person show here. Until then, ask in chat; the first tool that needs you will ask."
            testId="connectors-empty"
          />
        }
      />
      {(mine.data ?? []).length > 0 && (
        <p className="text-xs text-muted-foreground" data-testid="connectors-count">
          {plural((mine.data ?? []).length, 'connector')} · {connected} connected
        </p>
      )}
    </div>
  );

  return (
    <PageLayout
      icon={UserRound}
      title={MY_CONNECTORS}
      switcher
      description={`Apps that act as you in chat and in agents working for you, in ${team?.name ?? 'this team'}. Sign in once per team; disconnect here any time.`}
    >
      {body}
      <ConnectorSheet connector={shown} open={shown !== null} onOpenChange={(o) => !o && setOpen(null)} onConnect={(c, another) => connect.go(c, another)} onDisconnect={(c) => setEnding(c)} />
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
        entityType="connector"
        entityName={ending?.name}
        verb="Disconnect"
        testIdPrefix="my-connection"
        description={`Chat and agents working for you lose ${ending?.name ?? 'this app'} as you until you connect it again. The team account does not act for you; it serves only runs nobody started.`}
        isLoading={disconnect.isPending}
        onConfirm={async () => {
          if (!ending?.primaryAccountId) return;
          await disconnect.mutateAsync(ending.primaryAccountId);
          toast.success(`Disconnected from ${ending.name}`);
          setEnding(null);
          setOpen(null);
        }}
      />
    </PageLayout>
  );
}

export default function Page() {
  return <ConnectorsPage />;
}
