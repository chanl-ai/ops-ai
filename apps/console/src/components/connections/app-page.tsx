'use client';

import * as React from 'react';
import { Bot, ChevronDown, CircleCheck, ExternalLink, FileText, FlaskConical, KeyRound, Plug, Plus, RefreshCw, Sparkles, Users, Workflow } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import type { ColumnDef } from '@tanstack/react-table';

import { AppsTabs } from '@/components/connections/apps-tabs';
import { ConnectWindow, connectsInWindow } from '@/components/connections/connect-window';
import { HealthLine } from '@/components/connections/health-line';
import { AppStateBadge } from '@/components/connections/systems-grid';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ConnectSystemDialog, type ConnectMode } from '@/components/connections/connect-system-dialog';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ToolCallsView } from '@/components/tools/tool-calls-view';
import { UsedByCell } from '@/components/tools/used-by';
import { ListEmpty } from '@/components/shared/query-states';
import { useSignInWindow } from '@/components/connections/sign-in';
import { PageLayout } from '@/components/page-layout';
import { PluginUpdatePanel } from '@/components/connections/plugin-update-panel';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { ScrollTabsList } from '@/components/shared/setting/scroll-tabs';
import {
  type AppPage as AppData,
  type SystemCard,
  useAddAccount,
  useApp,
  useAppUsers,
  useChangeAccount,
  useConnectionKinds,
  usePinDefault,
  useSetTeamApp,
  useSignOutMine,
  useStartSignIn,
  useTestAccount,
} from '@/hooks/systems-queries';
import { useCopyResource, usePluginDocumentTypes, usePluginTemplates } from '@/hooks/plugin-update-queries';
import { useFlag } from '@/hooks/flag-queries';
import type { Kinds } from '@/lib/connect-plan';
import { plural, shortDate } from '@/lib/format';

type Connection = NonNullable<AppData['connection']>;

const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

const OK = 'border-success/40 bg-success/10 text-success-text';

function Logo({ name, logo }: { name: string; logo?: string | null }) {
  return (
    <Avatar className="size-9 rounded-md">
      {logo && <AvatarImage src={logo} alt="" />}
      <AvatarFallback className="rounded-md text-xs font-semibold">{initials(name)}</AvatarFallback>
    </Avatar>
  );
}

/** An account's state, as the final Apps design names them: Connected, Expired, Not signed in. */
function AccountState({ status }: { status: 'connected' | 'expired' | 'unsigned' }) {
  if (status === 'expired')
    return (
      <Badge variant="outline" className="border-warning/40 bg-warning/10 text-warning-text">
        Expired
      </Badge>
    );
  if (status === 'unsigned') return <Badge variant="outline">Not signed in</Badge>;
  return (
    <Badge variant="outline" className={OK}>
      Connected
    </Badge>
  );
}

/** The default account's keys, by their last test. */
function KeysState({ health }: { health: Connection['health'] }) {
  if (health?.status === 'failed') return <Badge variant="outline" className="border-destructive/40 bg-destructive/10 text-destructive">Failing</Badge>;
  if (health?.status === 'ok')
    return (
      <Badge variant="outline" className={OK}>
        <CircleCheck />
        Working
      </Badge>
    );
  return <Badge variant="outline">Not tested</Badge>;
}

/**
 * One app's page: a header with its one main action (Connect, Connected as, or Reconnect), then the tabs. Accounts
 * holds the team's shared logins, the sandbox among them; People holds each person's own sign-in. Everything comes
 * from one answer, GET /v1/apps/{id}.
 */
export function AppPageView({ appId }: { appId: string }) {
  const app = useApp(appId);
  const kinds = useConnectionKinds();
  const start = useStartSignIn();
  const [dialog, setDialog] = React.useState<{ mode: ConnectMode } | null>(null);
  // The Connect window, opened from the header's Connect: the small one when the app signs in through an OAuth app.
  const [connecting, setConnecting] = React.useState(false);
  const [another, setAnother] = React.useState(false);
  const [sandboxing, setSandboxing] = React.useState(false);
  // Several named accounts of one app (c-608) and sandbox accounts are behind their install flags; off, neither shows.
  const several = useFlag('several_accounts');
  const sandboxes = useFlag('sandbox_accounts');

  const test = useTestAccount();
  const signInWindow = useSignInWindow({
    onConnected: (m) => {
      toast.success(m.account ? `Connected as ${m.account}` : `${m.connection} is connected`);
      void app.refetch();
      // Connected once access is allowed; the first test runs after, and a failure shows on the account's row.
      const asked = signedInAs.current;
      if (asked === 'team') test.mutate({ appId, accountId: m.connectionId }, { onSettled: () => void app.refetch() });
    },
    onFailed: (why) => toast.error('The sign-in did not finish', { description: why }),
  });
  const signedInAs = React.useRef<'self' | 'team' | null>(null);

  if (app.isPending || kinds.isPending) return <RecordSkeleton />;
  if (app.isError) return <QueryError what="this app" error={app.error} onRetry={() => app.refetch()} retrying={app.isFetching} />;
  const data = app.data;
  const card = data.card as SystemCard;
  const conn = data.connection;
  const all = kinds.data as Kinds | undefined;
  const kind = all?.kinds.find((k) => k.id === conn?.authKind);
  // A built-in app runs inside Ops AI: it has no accounts to sign in, so no Accounts, People or Connect.
  const builtIn = card.kind === 'builtin' || card.kind === 'module';
  const installed = Boolean(card.appState) && card.appState !== 'not_installed';
  // People connect their own account only where the connection lets them; a team-only one shows its accounts alone.
  const signsIn = Boolean(kind?.signsIn) && conn?.signIn !== 'team';
  const accounts = data.accounts ?? [];
  // A team admin adds the app's sandbox account, which test runs use, once the app has its first account.
  const addsSandbox = sandboxes && card.mayManage && Boolean(conn) && installed && !card.sandboxId;

  const signIn = (account: 'self' | 'team', accountId = conn?.id) => {
    if (!accountId) return;
    // Opened in the click, before the call that starts the sign-in, so a pop-up blocker lets it through.
    const w = signInWindow.open(card.name, card.logo);
    if (!w) return;
    signedInAs.current = account;
    const run = () =>
      start.mutate({ appId, accountId, account }, { onSuccess: (s) => w.go(s, { appId, accountId }), onError: (e) => w.fail(e.message) });
    w.retry(run);
    run();
  };

  const tabs: [string, string][] = [
    ...(builtIn ? [] : ([['accounts', 'Accounts'], ['people', 'People']] as [string, string][])),
    ['tools', 'Tools'],
    ['resources', 'Resources'],
    ['secrets', 'Secrets'],
    ['logs', 'Logs'],
    ['settings', 'Settings'],
  ];

  return (
    <PageLayout
      icon={<Logo name={card.name} logo={card.logo} />}
      title={card.name}
      description={`${plural(card.toolsCount, 'tool')}${card.kindLabel ? ` · ${card.kindLabel}` : ''}`}
      breadcrumbs={[{ label: 'Apps', href: '/integrations' }, { label: card.name }]}
      // The Apps menu's tabs and a way back to the catalog, as the app page's frame draws them (Apps (final) group 4).
      backHref="/integrations"
      tabs={<AppsTabs />}
      badge={<AppStateBadge card={card} testId="app-status" />}
      actions={
        builtIn || card.appState === 'removed' ? undefined : (
          <HeaderAction
            app={data}
            signsIn={Boolean(kind?.signsIn)}
            onConnect={() => setConnecting(true)}
            onSignIn={signIn}
            onEdit={() => setDialog({ mode: 'edit' })}
            starting={start.isPending}
          />
        )
      }
      contentClassName="flex min-w-0 flex-col gap-4"
    >
      {card.appState === 'removed' && (
        <Alert variant="destructive" data-testid="app-removed">
          <AlertTitle>{`${card.name} is no longer installed`}</AlertTitle>
          <AlertDescription>{card.appStateReason}</AlertDescription>
        </Alert>
      )}
      {card.kind === 'plugin' && card.appState !== 'removed' && <PluginUpdatePanel appId={card.id} name={card.name} />}
      <Tabs defaultValue={tabs[0][0]} className="min-w-0">
        {/* Seven tabs are wider than a phone: the row scrolls sideways inside its box instead of clipping the last. */}
        <ScrollTabsList tabs={tabs.map(([value, label]) => ({ value, label }))} testId="app-tabs-row" triggerTestId={(v) => `app-tab-${v}`} />
        {!builtIn && (
          <TabsContent value="accounts">
            <AccountsTab
              app={data}
              signsIn={signsIn}
              onSignIn={signIn}
              actions={
                addsSandbox || (several && conn?.mayManage) ? (
                  <span className="flex flex-wrap gap-2">
                    {several && conn?.mayManage && (
                      <Button size="sm" variant="outline" onClick={() => setAnother(true)} data-testid="app-connect-another">
                        <Plus />
                        Add account
                      </Button>
                    )}
                    {addsSandbox && (
                      <Button size="sm" variant="outline" onClick={() => setSandboxing(true)} data-testid="app-add-sandbox">
                        <FlaskConical />
                        Add a sandbox account
                      </Button>
                    )}
                  </span>
                ) : undefined
              }
            />
          </TabsContent>
        )}
        {!builtIn && (
          <TabsContent value="people">
            <PeopleTab app={data} signsIn={signsIn} onConnectMine={() => signIn('self')} starting={start.isPending} />
          </TabsContent>
        )}
        <TabsContent value="tools">
          <ToolsTab app={data} />
        </TabsContent>
        <TabsContent value="resources">
          <ResourcesTab app={data} />
        </TabsContent>
        <TabsContent value="secrets">
          <SecretsTab app={data} onReconnect={() => setDialog({ mode: 'edit' })} />
        </TabsContent>
        <TabsContent value="logs">
          {/* The same call log as Tool calls, fixed to this app's tools. */}
          <div className="flex flex-col gap-2" data-testid="app-logs">
            <ToolCallsView fixed={{ moduleId: card.moduleIds }} totals={false} emptyText={`No call of ${card.name}’s tools yet.`} />
          </div>
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab app={data} kinds={all} onSetUp={() => setDialog({ mode: 'edit' })} />
        </TabsContent>
      </Tabs>
      {dialog && conn && (
        <ConnectSystemDialog
          // A plugin's account is set up with the plugin's own fields (its sign-in address, the team's own app).
          target={card.kind === 'plugin' && card.plugin ? { kind: 'plugin', card } : { kind: 'account', account: { appId, accountId: conn.id } }}
          mode={dialog.mode}
          open
          onOpenChange={(o) => !o && (setDialog(null), void app.refetch())}
        />
      )}
      {another && card.pluginId && all && connectsInWindow(card, all) ? (
        <ConnectWindow card={card} kinds={all} another open onOpenChange={(o) => !o && (setAnother(false), void app.refetch())} />
      ) : another && card.pluginId ? (
        <AnotherAccountDialog
          app={card.name}
          appId={appId}
          signInOptions={card.plugin?.signIn ?? []}
          onClose={() => setAnother(false)}
          onMade={() => {
            setAnother(false);
            void app.refetch();
          }}
        />
      ) : null}
      {sandboxing &&
        conn &&
        (all && connectsInWindow(card, all) ? (
          <ConnectWindow card={card} kinds={all} sandbox open onOpenChange={(o) => !o && (setSandboxing(false), void app.refetch())} />
        ) : (
          <ConnectSystemDialog
            // The same fields as the app's first connect, made as one more account of the app.
            target={card.kind === 'plugin' && card.plugin ? { kind: 'plugin', card, sandbox: true } : { kind: 'sandbox', appId, name: card.name, authKind: conn.authKind }}
            mode="connect"
            open
            onOpenChange={(o) => !o && (setSandboxing(false), void app.refetch())}
          />
        ))}
      {connecting &&
        (all && connectsInWindow(card, all) ? (
          <ConnectWindow card={card} kinds={all} open onOpenChange={(o) => !o && (setConnecting(false), void app.refetch())} />
        ) : (
          <ConnectSystemDialog
            target={
              card.kind === 'plugin' && card.plugin
                ? { kind: 'plugin', card }
                : conn
                  ? { kind: 'account', account: { appId, accountId: conn.id } }
                  : { kind: 'module', moduleId: card.moduleIds[0] ?? '', name: card.name }
            }
            mode="connect"
            open
            onOpenChange={(o) => !o && (setConnecting(false), void app.refetch())}
          />
        ))}
    </PageLayout>
  );
}

type Account = NonNullable<AppData['accounts']>[number];
const BROKEN = new Set(['expired', 'refused', 'revoked']);
const accountStatus = (a: Pick<Account, 'state'>) => (BROKEN.has(a.state) ? 'expired' : a.state === 'not_signed_in' ? 'unsigned' : 'connected');

/**
 * The header's one main action, from the team account's state: Connect while it is not signed in, Reconnect once its
 * sign-in expired, was refused or its test failed, and "Connected as …" once it works. Someone who does not manage the
 * team's apps reads that a team admin connects it. On an app each person signs in to, the caller's own sign-in is the
 * action once the team account works.
 */
function HeaderAction({
  app,
  signsIn,
  onConnect,
  onSignIn,
  onEdit,
  starting,
}: {
  app: AppData;
  signsIn: boolean;
  onConnect: () => void;
  onSignIn: (account: 'self' | 'team', accountId?: string) => void;
  onEdit: () => void;
  starting: boolean;
}) {
  const { card, connection: conn, me } = app;
  const team = (app.accounts ?? []).find((a) => a.default);
  const installed = Boolean(card.appState) && card.appState !== 'not_installed';
  const teamTestFailed = team?.test?.status === 'failed' || (card.appState === 'test_failed' && conn?.signIn === 'team');
  const broken = Boolean(team && (BROKEN.has(team.state) || teamTestFailed));
  const unsigned = !conn || !installed || !team || team.state === 'not_signed_in';
  // Where each person signs in with their own account and nobody signs in for the team, the caller's own is the action.
  if (installed && conn?.signIn === 'person') {
    if (!me.connected)
      return (
        <LoadingButton size="sm" isLoading={starting} onClick={() => onSignIn('self')} data-testid="app-connect-me">
          <ExternalLink />
          Connect my account
        </LoadingButton>
      );
    if (card.appState === 'test_failed')
      return (
        <Button size="sm" onClick={() => onSignIn('self')} data-testid="app-reconnect">
          <RefreshCw />
          Reconnect
        </Button>
      );
    return <ConnectedAs who={me.account} />;
  }
  if ((broken || unsigned) && !card.mayManage)
    return (
      <span className="text-sm text-muted-foreground" data-testid="app-admin-connects">
        A team admin connects this
      </span>
    );
  if (broken)
    return (
      <Button size="sm" onClick={() => (signsIn ? onSignIn('team', team?.id) : onEdit())} data-testid="app-reconnect">
        <RefreshCw />
        Reconnect
      </Button>
    );
  if (unsigned)
    return conn && installed && team && signsIn ? (
      // A team account made but never signed in (an earlier window closed, or the app turned off and on).
      <LoadingButton size="sm" isLoading={starting} onClick={() => onSignIn('team', team.id)} data-testid="app-sign-in-team">
        <ExternalLink />
        Connect
      </LoadingButton>
    ) : (
      <Button size="sm" onClick={onConnect} data-testid="app-connect">
        <Plug />
        Connect
      </Button>
    );
  return <ConnectedAs who={conn?.signedIn?.account ?? team?.name} />;
}

function ConnectedAs({ who }: { who?: string | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm" data-testid="app-connected-as">
      <CircleCheck className="size-4 text-success-text" />
      {who ? `Connected as ${who}` : 'Connected'}
    </span>
  );
}

/** Accounts: the team's shared logins, the default first and a sandbox marked, with Add account. */
function AccountsTab({
  app,
  signsIn,
  onSignIn,
  actions,
}: {
  app: AppData;
  signsIn: boolean;
  onSignIn: (account: 'self' | 'team', accountId?: string) => void;
  actions?: React.ReactNode;
}) {
  const { card, connection: conn } = app;
  const accounts = app.accounts ?? [];
  const pin = usePinDefault();
  const failure = card.appState === 'test_failed' ? (card.appStateReason ?? 'no reason given') : null;
  // A row's failed test: the account's own when the answer carries it, else the app's for its default account.
  const testFailed = (a: Account) => (a.test?.status === 'failed' ? a.test.message || 'no reason given' : a.default ? failure : null);
  return (
    <Section title="Accounts" description="Calls use the default account unless a step names another." flush actions={actions}>
      {!conn || !accounts.length ? (
        <div className="p-4" data-testid="app-not-connected">
          <ListEmpty icon={Plug} noun="accounts" filtered={false} description={`${card.name} has no account yet. Calls stay off until one is connected.`} />
        </div>
      ) : (
        <Rows testId="app-accounts">
          {accounts.map((a) => (
            <Row
              key={a.id}
              wrap
              leading={<Logo name={card.name} logo={card.logo} />}
              title={
                <span className="flex flex-wrap items-center gap-2" data-testid={`account-${a.name}`}>
                  {a.name}
                  {a.default && <Badge variant="secondary">Default</Badge>}
                  {a.sandbox && (
                    <Badge variant="outline" data-testid={`account-sandbox-${a.name}`}>
                      Sandbox
                    </Badge>
                  )}
                  <AccountState status={accountStatus(a)} />
                  {a.pinned && accounts.length > 1 && <Badge variant="outline">Your default</Badge>}
                </span>
              }
              description={
                testFailed(a) ? (
                  <span className="text-warning-text" data-testid={a.default ? 'app-test-failed' : `account-test-failed-${a.name}`}>
                    Signed in, but a test call failed: {testFailed(a)}
                  </span>
                ) : (
                  (a.statusDetail ?? undefined)
                )
              }
              trailing={
                testFailed(a) && a.mine && conn.signIn !== 'team' ? (
                  // The person's own sign-in failed its test: they sign in again as themselves.
                  <Button size="sm" onClick={() => onSignIn('self', a.id)} data-testid={`account-reconnect-mine-${a.name}`}>
                    <RefreshCw />
                    Reconnect
                  </Button>
                ) : a.default ? undefined : conn.mayManage && (BROKEN.has(a.state) || a.status === 'needs_reconnect' || testFailed(a)) ? (
                  // The default account's Reconnect and Connect are the header's; another account's are on its row.
                  <Button size="sm" onClick={() => onSignIn('team', a.id)} data-testid={`account-reconnect-${a.name}`}>
                    <RefreshCw />
                    Reconnect
                  </Button>
                ) : conn.mayManage && a.state === 'not_signed_in' && !a.mine ? (
                  <Button size="sm" onClick={() => onSignIn('team', a.id)} data-testid={`account-sign-in-${a.name}`}>
                    <ExternalLink />
                    Sign in
                  </Button>
                ) : a.mine && !a.pinned && accounts.length > 1 ? (
                  <LoadingButton
                    size="sm"
                    variant="outline"
                    isLoading={pin.isPending && pin.variables?.accountId === a.id}
                    onClick={() => pin.mutate({ appId: card.id, accountId: a.id }, { onError: (e) => toast.error('Couldn’t make it your default', { description: e.message }) })}
                    data-testid={`account-pin-${a.name}`}
                  >
                    Make my default
                  </LoadingButton>
                ) : !a.mine && signsIn ? (
                  <Button size="sm" variant="outline" onClick={() => onSignIn('self', a.id)} data-testid={`account-connect-${a.name}`}>
                    <ExternalLink />
                    Connect my account
                  </Button>
                ) : undefined
              }
            />
          ))}
        </Rows>
      )}
    </Section>
  );
}

const PERSON_STATE = {
  connected: { label: 'Connected', className: OK },
  expired: { label: 'Expired', className: 'border-warning/40 bg-warning/10 text-warning-text' },
  refused: { label: 'Refused', className: 'border-destructive/40 bg-destructive/10 text-destructive' },
} as const;

/**
 * People: each person who signed in with their own login, on which account, when, and its state, as the API joins
 * them (a team admin reads everyone's, anyone else their own). The caller connects or disconnects their own here.
 */
function PeopleTab({ app, signsIn, onConnectMine, starting }: { app: AppData; signsIn: boolean; onConnectMine: () => void; starting: boolean }) {
  const { card, connection: conn, me } = app;
  const signOut = useSignOutMine();
  const people = app.people ?? [];
  // On an app only each person signs in to, the header carries Connect my account; here it is the second way in.
  const connectsHere = signsIn && !me.connected && conn?.signIn !== 'person';
  return (
    <Section
      title="People"
      description={signsIn ? 'Each person who signed in with their own login. Calls they start run as them.' : `Every call signs in as a team account; nobody signs in to ${card.name} with their own login.`}
      flush
      actions={
        connectsHere ? (
          <LoadingButton size="sm" isLoading={starting} onClick={onConnectMine} data-testid="app-connect-me">
            <ExternalLink />
            Connect my account
          </LoadingButton>
        ) : undefined
      }
    >
      {signsIn && (
        <p className="border-b px-4 py-3 text-sm" data-testid="app-me-state">
          {me.connected ? `Connected as ${me.account ?? 'you'}` : 'You have not connected your own account.'}
        </p>
      )}
      {people.length ? (
        <Rows testId="app-people">
          {people.map((p) => (
            <Row
              key={`${p.accountId}:${p.personId}`}
              wrap
              leading={<Logo name={p.account ?? p.personId} />}
              title={
                <span className="flex flex-wrap items-center gap-2" data-testid={`person-${p.personId}`}>
                  {p.account ?? p.personId}
                  {p.mine && <Badge variant="secondary">You</Badge>}
                  <Badge variant="outline" className={PERSON_STATE[p.state].className}>
                    {PERSON_STATE[p.state].label}
                  </Badge>
                </span>
              }
              description={
                p.testFailed ? (
                  <span className="text-warning-text">Signed in, but a test call failed: {p.testFailed}</span>
                ) : (
                  `${p.accountName}${p.since ? ` · signed in ${shortDate(p.since)}` : ''}`
                )
              }
              trailing={
                p.mine && conn ? (
                  <LoadingButton
                    size="sm"
                    variant="ghost"
                    isLoading={signOut.isPending}
                    onClick={() => signOut.mutate(p.accountId, { onError: (e) => toast.error('Couldn’t disconnect', { description: e.message }) })}
                    data-testid={p.accountId === conn.id ? 'app-disconnect' : `person-disconnect-${p.accountName}`}
                  >
                    Disconnect
                  </LoadingButton>
                ) : undefined
              }
            />
          ))}
        </Rows>
      ) : (
        <div className="p-4">
          <ListEmpty icon={Users} noun="people" filtered={false} description="Nobody has signed in with their own login yet." />
        </div>
      )}
    </Section>
  );
}

type AppTool = AppData['tools'][number];

const TOOL_COLUMNS: ColumnDef<AppTool>[] = [
  {
    accessorKey: 'title',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Tool" />,
    cell: ({ row }) => (
      <span>
        <span className="font-medium">{row.original.title}</span> <code className="text-xs text-muted-foreground">{row.original.name}</code>
      </span>
    ),
  },
  {
    accessorKey: 'access',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Access" />,
    cell: ({ row }) => <Badge variant={row.original.access === 'write' ? 'default' : 'secondary'}>{row.original.access === 'write' ? 'Write' : 'Read'}</Badge>,
  },  {
    id: 'usedBy',
    header: 'Used by',
    cell: ({ row }) =>
      row.original.usedBy ? (
        <UsedByCell usedBy={row.original.usedBy} testId={`app-tool-used-by-${row.original.name}`} />
      ) : (
        <span className="text-xs text-muted-foreground" data-testid={`app-tool-used-by-${row.original.name}`}>
          Not known right now
        </span>
      ),
  },
];

function ToolsTab({ app }: { app: AppData }) {
  return (
    <div className="flex flex-col gap-2" data-testid="app-tools">
      <div>
        <h3 className="text-sm font-semibold">Tools</h3>
        <p className="text-sm text-muted-foreground">
          {plural(app.tools.length, 'tool')}, shared by every team that connects {app.card.name}.
        </p>
      </div>
      <DataTableWithViews
        columns={TOOL_COLUMNS}
        data={app.tools}
        getRowId={(t) => t.name}
        searchColumn="title"
        searchPlaceholder="Filter tools"
        emptyState={<ListEmpty icon={KeyRound} noun="tools" filtered={false} description={`${app.card.name} has no tools.`} />}
      />
    </div>
  );
}

const COPY_HREF = { agent: '/agents', skill: '/skills', workflow: '/workflows', document_type: '/document-types' } as const;
const RESOURCE_ICON = { agent: Bot, skill: Sparkles, workflow: Workflow, document_type: FileText } as const;

/**
 * Resources (U5): the agents, skills, workflows and document types the app brings, each from the service that keeps
 * that kind with whether the team has its own copy. Add to team makes the copy and opens it; Added opens it again.
 */
function ResourcesTab({ app }: { app: AppData }) {
  const router = useRouter();
  const source = app.card.pluginId ? `plugin:${app.card.pluginId}` : '';
  const agents = usePluginTemplates(source);
  const documents = usePluginDocumentTypes(source);
  const copy = useCopyResource(source);
  if (!app.card.pluginId || (!app.skills.length && !agents.isPending && !documents.isPending && !agents.data?.length && !documents.data?.length))
    return (
      <Section>
        <p className="text-sm text-muted-foreground" data-testid="app-skills-none">
          No resources: {app.card.name} brings tools only.
        </p>
      </Section>
    );
  const rows = [
    ...(agents.data ?? []).map((t) => ({ id: t.id, kind: t.kind, title: t.title, copies: t.installed.copies, service: 'agents' as const })),
    ...(documents.data ?? []).map((t) => ({ id: t.id, kind: t.kind, title: t.title, copies: t.installed.copies, service: 'documents' as const })),
  ];
  const open = (r: (typeof rows)[number], added: boolean) =>
    copy.mutate(
      { id: r.id, service: r.service },
      {
        onSuccess: (made) => {
          if (!added) toast.success(`Added ${r.title} to your team`);
          router.push(`${COPY_HREF[made.copy.kind]}/${made.copy.recordId}`);
        },
        onError: (e) => toast.error(`Couldn’t add ${r.title}`, { description: e.message }),
      },
    );
  return (
    <Section title="Resources" description="Agents, skills, workflows and document types the app brings. Added ones are your team’s own copies." flush>
      {agents.isPending || documents.isPending ? (
        <div className="flex flex-col gap-2 p-4" aria-busy="true">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : agents.isError || documents.isError ? (
        <div className="p-4">
          <QueryError what="the app’s resources" error={agents.error ?? documents.error} onRetry={() => (void agents.refetch(), void documents.refetch())} retrying={agents.isFetching || documents.isFetching} />
        </div>
      ) : (
        <Rows testId="app-skills">
          {rows.map((r) => {
            const Icon = RESOURCE_ICON[r.kind];
            const added = r.copies > 0;
            return (
              <Row
                key={`${r.service}-${r.id}`}
                leading={<Icon className="size-4 text-muted-foreground" />}
                title={
                  <span className="flex flex-wrap items-center gap-2" data-testid={`resource-${r.id}`}>
                    {r.title}
                    <Badge variant="secondary">{r.kind.replace('_', ' ')}</Badge>
                  </span>
                }
                trailing={
                  <LoadingButton
                    size="sm"
                    variant={added ? 'ghost' : 'outline'}
                    isLoading={copy.isPending && copy.variables?.id === r.id}
                    onClick={() => open(r, added)}
                    data-testid={`resource-${added ? 'open' : 'add'}-${r.id}`}
                  >
                    {added ? 'Added · Open' : 'Add to team'}
                  </LoadingButton>
                }
              />
            );
          })}
        </Rows>
      )}
    </Section>
  );
}

/**
 * Secrets: which app credential the app signs in with (Ops AI's app, or the team's own under Credentials) and the
 * secrets its tools use. Values are never shown.
 */
function SecretsTab({ app, onReconnect }: { app: AppData; onReconnect: () => void }) {
  const conn = app.connection;
  const credential = app.card.credential;
  const sealed = Object.entries(conn?.secrets ?? {}).filter(([field, v]) => v.set && field !== 'clientSecret');
  return (
    <Section title="Secrets" description="The app credential it signs in with, and the secrets its tools use. Values are never shown." flush>
      <Rows testId="app-secrets">
        {credential && (
          <Row
            wrap
            leading={<KeyRound className="size-4 text-muted-foreground" />}
            title={<span data-testid="app-credential-name">{`App credential · ${credential.type === 'ops_ai' ? 'Ops AI’s app' : credential.name}`}</span>}
            description={conn?.signedIn ? `Signed in${conn.signedIn.account ? ` as ${conn.signedIn.account}` : ''} · refreshes on use` : 'Not signed in yet'}
            trailing={
              <Button size="sm" variant="ghost" asChild>
                <Link href="/integrations/credentials" data-testid="app-credential-link">
                  Credentials
                </Link>
              </Button>
            }
          />
        )}
        {sealed.map(([name]) => (
          <Row key={name} leading={<KeyRound className="size-4 text-muted-foreground" />} title={name} description="Sealed" />
        ))}
        {!credential && !sealed.length && <Row title="Nothing saved yet" />}
      </Rows>
      {conn?.mayManage && (credential || sealed.length > 0) && (
        <div className="border-t p-3">
          <Button size="sm" variant="outline" onClick={onReconnect}>
            Replace keys or sign in again
          </Button>
        </div>
      )}
    </Section>
  );
}

function SettingsTab({ app, kinds, onSetUp }: { app: AppData; kinds?: Kinds; onSetUp: () => void }) {
  const conn = app.connection;
  const change = useChangeAccount();
  const test = useTestAccount();
  const setTeamApp = useSetTeamApp();
  const kind = kinds?.kinds.find((k) => k.id === conn?.authKind);
  const [own, setOwn] = React.useState({ clientId: '', clientSecret: '' });
  if (!conn) return null;
  const account = { appId: app.card.id, accountId: conn.id };
  const teamSigned = Boolean(conn.signedIn);
  const everyone = conn.signIn !== 'team';
  const platform = Boolean(conn.platformApp);
  const keysSet = Object.keys(conn.settings).length > 0 || Object.values(conn.secrets).some((v) => v.set) || teamSigned;
  const flip = (on: boolean) =>
    change.mutate(
      { ...account, body: { revision: conn.revision, signIn: on ? (teamSigned ? 'person_or_team' : 'person') : 'team', teamBackup: on && teamSigned } },
      { onError: (e) => toast.error('Couldn’t change who signs in', { description: e.message }) },
    );
  return (
    <div className="flex flex-col gap-4">
      {kind?.perPerson && conn.mayManage && (
        <Section title="Who signs in" flush>
          <div className="flex items-center gap-3 p-4">
            <label htmlFor="app-everyone" className="min-w-0 flex-1 text-sm">
              <span className="block font-medium">Everyone signs in with their own account</span>
              <span className="block text-xs text-muted-foreground">Off, every call runs as the team account.</span>
            </label>
            <Switch id="app-everyone" checked={everyone} disabled={change.isPending} onCheckedChange={flip} data-testid="app-everyone" />
          </div>
        </Section>
      )}
      {kind?.signsIn && app.card.pluginId && conn.mayManage && (
        <Collapsible className="rounded-lg border bg-card">
          <CollapsibleTrigger className="flex w-full items-center gap-3 p-4 text-left" data-testid="app-own-row">
            <KeyRound className="size-4 text-muted-foreground" />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium">Use your own app</span>
              <span className="block text-xs text-muted-foreground">{platform ? 'Using Ops AI’s app' : 'Using your own app'}</span>
            </span>
            <ChevronDown className="size-4 text-muted-foreground" />
          </CollapsibleTrigger>
          <CollapsibleContent className="flex flex-col gap-3 border-t p-4" data-testid="app-credentials">
            <div className="grid gap-3 sm:grid-cols-2">
              <FormField id="own-client-id" label="Client ID">
                <Input id="own-client-id" value={own.clientId} onChange={(e) => setOwn((o) => ({ ...o, clientId: e.target.value }))} />
              </FormField>
              <FormField id="own-client-secret" label="Client secret">
                <Input id="own-client-secret" type="password" autoComplete="off" value={own.clientSecret} onChange={(e) => setOwn((o) => ({ ...o, clientSecret: e.target.value }))} placeholder="Sealed on save" />
              </FormField>
            </div>
            {kinds?.redirectUri && (
              <p className="text-sm">
                <span className="text-muted-foreground">Return address to register: </span>
                <code className="break-all">{kinds.redirectUri}</code>
              </p>
            )}
            <p className="text-xs text-warning-text">Changing the app or its permissions makes everyone connect again.</p>
            <div>
              <LoadingButton
                size="sm"
                isLoading={setTeamApp.isPending}
                disabled={!own.clientId.trim()}
                onClick={() =>
                  setTeamApp.mutate(
                    { appId: app.card.id, body: { enabled: true, sandbox: false, clientId: own.clientId.trim(), ...(own.clientSecret ? { clientSecret: own.clientSecret } : {}) } },
                    { onSuccess: () => toast.success('Saved: sign in again with your own app'), onError: (e) => toast.error('Couldn’t save the app', { description: e.message }) },
                  )
                }
                data-testid="app-own-save"
              >
                Save
              </LoadingButton>
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}
      <Section title="Keys" description="The default account’s settings and keys. Each account keeps its own." flush>
        <Rows testId="app-keys">
          <Row
            wrap
            leading={<KeyRound className="size-4 text-muted-foreground" />}
            title={
              <span className="flex flex-wrap items-center gap-2" data-testid="app-keys-state" data-status={keysSet ? (conn.health?.status ?? 'untested') : 'unset'}>
                {conn.name} {keysSet ? <KeysState health={conn.health} /> : <Badge variant="outline">Not set</Badge>}
              </span>
            }
            description={conn.health ? undefined : keysSet ? 'Not tested yet' : 'Not set'}
            trailing={
              conn.mayManage ? (
                <span className="flex flex-wrap gap-2">
                  {keysSet && (
                    <LoadingButton
                      size="sm"
                      variant="outline"
                      isLoading={test.isPending}
                      onClick={() => test.mutate(account, { onError: (x) => toast.error(`Couldn’t test ${conn.name}`, { description: x.message }) })}
                      data-testid="app-test"
                    >
                      Test
                    </LoadingButton>
                  )}
                  {/* Keys and sign-in settings change in the Connect window, on the account. */}
                  <Button size="sm" variant={keysSet ? 'ghost' : 'outline'} onClick={onSetUp} data-testid="app-edit">
                    {keysSet ? 'Edit' : 'Set up'}
                  </Button>
                </span>
              ) : undefined
            }
          >
            {conn.health && <HealthLine health={conn.health} />}
            {/* A test the service refused (a 400 before anything is sent) says why on the row; nothing else would. */}
            {test.isError && (
              <p className="text-sm text-destructive" data-testid="app-keys-error">
                {test.error.message}
              </p>
            )}
            {conn.certificate && (
              // A signed client's certificate: its thumbprint and expiry, never its key (the key is never sent back).
              <p className="flex flex-wrap items-center gap-2 text-sm" data-testid="app-certificate">
                <span className="text-muted-foreground">Signing certificate</span>
                <code className="min-w-0 break-all text-xs">{conn.certificate.thumbprint}</code>
                <span>expires {shortDate(conn.certificate.notAfter)}</span>
                {conn.certificate.expiresSoon && <Badge variant="outline">Expires soon</Badge>}
              </p>
            )}
          </Row>
        </Rows>
      </Section>
      {app.card.pluginId && conn.mayManage && <TurnOffSection name={app.card.name} appId={app.card.id} />}
    </div>
  );
}

/**
 * Turn off (group K): stops the app's tools for this team, keeping its accounts and what the team added. The window
 * names every agent and workflow using its tools first, read when it opens; when the service cannot tell, it says so.
 */
function TurnOffSection({ name, appId }: { name: string; appId: string }) {
  const [open, setOpen] = React.useState(false);
  const users = useAppUsers(open ? appId : null);
  const setTeamApp = useSetTeamApp();
  const listed = [...(users.data?.agents ?? []).map((a) => ({ ...a, what: 'agent' as const })), ...(users.data?.workflows ?? []).map((w) => ({ ...w, what: 'workflow' as const }))];
  return (
    <Section title="Turn off" flush>
      <div className="flex flex-wrap items-center gap-3 p-4">
        <span className="min-w-0 flex-1 text-sm text-muted-foreground">Its tools stop for this team; its accounts and what you added stay.</span>
        <Button size="sm" variant="outline" onClick={() => setOpen(true)} data-testid="app-off">
          Turn off {name}
        </Button>
      </div>
      <DialogShell
        open={open}
        onOpenChange={setOpen}
        size="sm"
        title={`Turn off ${name}?`}
        description="These use its tools and stop working until it is turned on again."
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <LoadingButton
              variant="destructive"
              isLoading={setTeamApp.isPending}
              disabled={users.isPending || users.isError}
              onClick={() =>
                setTeamApp.mutate(
                  { appId, body: { enabled: false, sandbox: false } },
                  { onSuccess: () => (setOpen(false), toast.success(`${name} is off for this team`)), onError: (e) => toast.error(`Couldn’t turn off ${name}`, { description: e.message }) },
                )
              }
              data-testid="app-off-confirm"
            >
              Turn off
            </LoadingButton>
          </>
        }
      >
        <div data-testid="app-off-users">
          {users.isPending ? (
            <div className="flex flex-col gap-2" aria-busy="true">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : users.isError ? (
            <QueryError what={`what uses ${name}`} error={users.error} onRetry={() => users.refetch()} retrying={users.isFetching} />
          ) : listed.length ? (
            <Rows>
              {listed.map((u) => (
                <Row
                  key={`${u.what}:${u.id}`}
                  leading={u.what === 'agent' ? <Bot className="size-4 text-muted-foreground" /> : <Workflow className="size-4 text-muted-foreground" />}
                  title={u.name}
                  description={`${u.what === 'agent' ? 'Agent' : 'Workflow'} · ${plural(u.tools.length, 'tool')}`}
                />
              ))}
            </Rows>
          ) : (
            <p className="text-sm text-muted-foreground" data-testid="app-off-none">
              No agent or workflow uses its tools.
            </p>
          )}
        </div>
      </DialogShell>
    </Section>
  );
}


/**
 * Connect another account: a second org or a second account of the same app, under its own name, with the first's
 * contract; the system's own page then asks to allow access for it. Calls keep the default unless they name it.
 */
function AnotherAccountDialog({ app, appId, signInOptions, onClose, onMade }: { app: string; appId: string; signInOptions: string[]; onClose: () => void; onMade: (id: string) => void }) {
  const add = useAddAccount();
  const [name, setName] = React.useState('');
  const save = () =>
    add.mutate(
      {
        appId,
        // Each person may connect their own account of it too, when the app offers that, as for the first.
        body: { name: name.trim(), sandbox: false, ...(signInOptions.includes('person_or_team') ? { signIn: 'person_or_team' } : {}) },
      },
      { onSuccess: (made) => onMade(String(made.id)), onError: (e) => toast.error('Couldn’t add the account', { description: e.message }) },
    );
  return (
    <DialogShell
      open
      onOpenChange={(o) => !o && onClose()}
      size="sm"
      title="Connect another account"
      description={`Another ${app} account for this team, with its own name.`}
      data-testid="another-dialog"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <LoadingButton isLoading={add.isPending} disabled={!name.trim()} onClick={save} data-testid="another-connect">
            <ExternalLink />
            Connect
          </LoadingButton>
        </>
      }
    >
      <FormField id="another-name" label="Name" hint="Steps and tools pick an account by this name.">
        <Input id="another-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={`${app} · EU org`} />
      </FormField>
    </DialogShell>
  );
}
