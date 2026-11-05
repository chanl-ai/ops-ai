'use client';

import * as React from 'react';
import { AppCredentialPicker } from '@/components/connections/app-credential-picker';
import { ResourcesTab } from '@/components/connections/app-resources';
import { AuthConfigsTab, type AuthConfig } from '@/components/connections/app-auth-configs';
import { Bot, ChevronDown, CircleCheck, ExternalLink, FlaskConical, KeyRound, Plug, RefreshCw, Workflow } from 'lucide-react';
import { toast } from 'sonner';

import type { ColumnDef } from '@tanstack/react-table';

import { ConnectWindow, connectsInWindow } from '@/components/connections/connect-window';
import { HealthLine } from '@/components/connections/health-line';
import { AppStateBadge } from '@/components/connections/systems-grid';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { ConnectSystemDialog, type ConnectMode } from '@/components/connections/connect-system-dialog';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ToolCallsView } from '@/components/tools/tool-calls-view';
import { GrantToAgentDialog } from '@/components/tools/grant-to-agent-dialog';
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
  useSetTeamApp,
  useStartSignIn,
  useTestAccount,
} from '@/hooks/systems-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { useTeam } from '@/hooks/use-team';
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
  // The auth config Add account or Connect opens the Connect window on: its id, or null for Ops AI's own app.
  const [on, setOn] = React.useState<string | null | undefined>(undefined);
  const { team } = useTeam();
  const [sandboxing, setSandboxing] = React.useState(false);

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
  const configs = data.authConfigs ?? [];
  const accounts = configs.flatMap((c) => c.accounts ?? []);
  // Connect opens on the default account's config; Ops AI's own app is no credential.
  const credentialOf = (c?: AuthConfig) => (c && c.type === 'own' ? c.id : null);
  const defaultConfig = configs.find((c) => c.default);
  const addAccount = (c: AuthConfig) => (setOn(credentialOf(c)), card.connectionId ? setAnother(true) : setConnecting(true));
  // A team admin adds the app's sandbox account, which test runs use, once the app has its first account.
  const addsSandbox = card.mayManage && Boolean(conn) && installed && !card.sandboxId;

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
    ...(builtIn ? [] : ([['auth', 'Auth configs']] as [string, string][])),
    ['tools', 'Tools'],
    ['resources', 'Resources'],
    ['logs', 'Logs'],
    ['settings', 'Settings'],
  ];

  return (
    <PageLayout
      icon={<Logo name={card.name} logo={card.logo} />}
      title={card.name}
      description={`${plural(card.toolsCount, 'tool')}${card.kindLabel ? ` · ${card.kindLabel}` : ''}`}
      breadcrumbs={[{ label: 'Apps', href: '/integrations' }, { label: card.name }]}
      backHref="/integrations"
      badge={<AppStateBadge card={card} testId="app-status" />}
      actions={
        builtIn || card.appState === 'removed' ? undefined : (
          <HeaderAction
            app={data}
            signsIn={Boolean(kind?.signsIn)}
            onConnect={() => (setOn(credentialOf(defaultConfig)), setConnecting(true))}
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
          <TabsContent value="auth" className="flex flex-col gap-4">
            {addsSandbox && (
              <div className="flex justify-end">
                <Button size="sm" variant="outline" onClick={() => setSandboxing(true)} data-testid="app-add-sandbox">
                  <FlaskConical />
                  Add a sandbox account
                </Button>
              </div>
            )}
            <AuthConfigsTab app={data} team={team?.name ?? 'The team'} onAddAccount={addAccount} onSignIn={signIn} />
          </TabsContent>
        )}
        <TabsContent value="tools">
          <ToolsTab app={data} />
        </TabsContent>
        <TabsContent value="resources">
          <ResourcesTab appName={data.card.name} pluginId={data.card.pluginId} onConnect={() => setConnecting(true)} />
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
        <ConnectWindow card={card} kinds={all} another credential={on} taken={accounts.map((a) => a.name)} open onOpenChange={(o) => !o && (setAnother(false), void app.refetch())} />
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
          <ConnectWindow card={card} kinds={all} credential={on} taken={accounts.map((a) => a.name)} open onOpenChange={(o) => !o && (setConnecting(false), void app.refetch())} />
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

type Account = NonNullable<NonNullable<AppData['authConfigs']>[number]['accounts']>[number];
const BROKEN = new Set(['expired', 'refused', 'revoked']);

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
  const team = (app.authConfigs ?? []).flatMap((c) => c.accounts ?? []).find((a) => a.default);
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
    return <ConnectedAs account={team?.name} who={me.account} />;
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
  return <ConnectedAs account={team?.name} who={conn?.signedIn?.account} />;
}

/** Connected, with the default account's name and, when the system said, whom it signed in as. */
function ConnectedAs({ account, who }: { account?: string | null; who?: string | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm" data-testid="app-connected-as">
      <CircleCheck className="size-4 text-success-text" />
      {['Connected', account ? ` · ${account}` : '', who ? ` as ${who}` : ''].join('')}
    </span>
  );
}

type AppTool = AppData['tools'][number] & { onGrant?: (t: AppTool) => void };

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
  },
  {
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
  {
    id: 'grant',
    cell: ({ row }) =>
      row.original.onGrant ? (
        <Button size="sm" variant="outline" onClick={() => row.original.onGrant?.(row.original)} data-testid={`app-tool-grant-${row.original.name}`}>
          <Bot />
          Grant to agent
        </Button>
      ) : null,
    enableHiding: false,
  },
];

/** The app's tools by title, who uses each, and Grant to agent for someone who builds agents. */
function ToolsTab({ app }: { app: AppData }) {
  const canBuild = useCanBuild();
  const [granting, setGranting] = React.useState<AppTool | null>(null);
  const rows = React.useMemo(() => app.tools.map((t): AppTool => ({ ...t, onGrant: canBuild ? setGranting : undefined })), [app.tools, canBuild]);
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
        data={rows}
        getRowId={(t) => t.name}
        searchColumn="title"
        searchPlaceholder="Filter tools"
        emptyState={<ListEmpty icon={KeyRound} noun="tools" filtered={false} description={`${app.card.name} has no tools.`} />}
      />
      <GrantToAgentDialog tool={granting && { id: granting.name, title: granting.title }} onOpenChange={(o) => !o && setGranting(null)} />
    </div>
  );
}

function SettingsTab({ app, kinds, onSetUp }: { app: AppData; kinds?: Kinds; onSetUp: () => void }) {
  const conn = app.connection;
  const change = useChangeAccount();
  const test = useTestAccount();
  const setTeamApp = useSetTeamApp();
  const kind = kinds?.kinds.find((k) => k.id === conn?.authKind);
  const [own, setOwn] = React.useState<string | null | undefined>(undefined);
  if (!conn) return null;
  const account = { appId: app.card.id, accountId: conn.id };
  const teamSigned = Boolean(conn.signedIn);
  const everyone = conn.signIn !== 'team';
  const platform = !conn.credentialId;
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
            <AppCredentialPicker
              app={app.card.id}
              value={own === undefined ? (conn.credentialId ?? null) : own}
              onChange={setOwn}
              platform={Boolean(app.card.plugin?.platformApp)}
              id="own-credential"
              testId="app-own-credential"
            />
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
                disabled={own === undefined || own === (conn.credentialId ?? null)}
                onClick={() =>
                  setTeamApp.mutate(
                    { appId: app.card.id, body: { enabled: true, sandbox: false, credentialId: own ?? null } },
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
      <Section title="Keys" description="The default account’s settings and keys." flush>
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
