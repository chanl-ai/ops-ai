'use client';

import * as React from 'react';
import { Bot, ChevronDown, CircleCheck, ExternalLink, FileText, FlaskConical, Globe, KeyRound, Plug, Plus, RefreshCw, Sparkles, Workflow } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import type { ColumnDef } from '@tanstack/react-table';

import { AppsTabs } from '@/components/connections/apps-tabs';
import { ConnectWindow, connectsInWindow } from '@/components/connections/connect-window';
import { testFailure } from '@/components/connections/systems-grid';
import { ConnectSystemDialog, type ConnectMode } from '@/components/connections/connect-system-dialog';
import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ToolCallsView } from '@/components/tools/tool-calls-view';
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  type AppPage as AppData,
  useAddAccount,
  useApp,
  useAppUsers,
  useChangeConnection,
  useConnectionKinds,
  usePinDefault,
  useSetTeamPlugin,
  useSignOutMine,
  useStartSignIn,
  useTestEnvironment,
} from '@/hooks/systems-queries';
import { useSession } from '@/hooks/auth-queries';
import { useCopyResource, usePluginDocumentTypes, usePluginTemplates } from '@/hooks/plugin-update-queries';
import { useFlag } from '@/hooks/flag-queries';
import { keyed, leading, type Kinds } from '@/lib/connect-plan';
import { plural, relativeTime, shortDate } from '@/lib/format';

type Connection = NonNullable<AppData['connection']>;
type Env = Connection['environments'][string];

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

/** An environment's state from its last test. */
function EnvState({ env }: { env?: Env }) {
  if (!env?.set) return <Badge variant="outline">Not set</Badge>;
  if (env.health?.status === 'failed') return <Badge variant="outline" className="border-destructive/40 bg-destructive/10 text-destructive">Failing</Badge>;
  if (env.health?.status === 'ok')
    return (
      <Badge variant="outline" className={OK}>
        <CircleCheck />
        Working
      </Badge>
    );
  return <Badge variant="outline">Not tested</Badge>;
}

/**
 * One app's page (c-607): who you are signed in as and one button to connect your own
 * account, the team's account, then Tools, Skills, Sign-in and secrets, Logs and Settings. Everything comes from one
 * answer, GET /v1/apps/{id}.
 */
export function AppPageView({ appId }: { appId: string }) {
  const app = useApp(appId);
  const { session } = useSession();
  const kinds = useConnectionKinds();
  const start = useStartSignIn();
  const signOut = useSignOutMine();
  const [dialog, setDialog] = React.useState<{ mode: ConnectMode; environment?: string } | null>(null);
  // The Connect window, opened from the Not connected state: the small one when the app signs in through Ops AI's app.
  const [connecting, setConnecting] = React.useState(false);
  const [another, setAnother] = React.useState(false);
  const pin = usePinDefault();
  // Several named accounts of one app (c-608) are behind the several_accounts install flag; off, one account.
  const several = useFlag('several_accounts');

  const test = useTestEnvironment();
  const signInWindow = useSignInWindow({
    onConnected: (m) => {
      toast.success(m.account ? `Connected as ${m.account}` : `${m.connection} is connected`);
      void app.refetch();
      // Connected once access is allowed; the first test runs after, and a failure shows on the account's row.
      const asked = signedInAs.current;
      if (asked?.account === 'team') test.mutate({ connectionId: m.connectionId, environment: asked.environment }, { onSettled: () => void app.refetch() });
    },
    onFailed: (why) => toast.error('The sign-in did not finish', { description: why }),
  });
  const signedInAs = React.useRef<{ account: 'self' | 'team'; environment: string } | null>(null);

  if (app.isPending || kinds.isPending) return <RecordSkeleton />;
  if (app.isError) return <QueryError what="this app" error={app.error} onRetry={() => app.refetch()} retrying={app.isFetching} />;
  const data = app.data;
  const card = data.card;
  const conn = data.connection;
  const all = kinds.data as Kinds | undefined;
  const kind = all?.kinds.find((k) => k.id === conn?.authKind);
  const envs = all ? keyed(all) : [];
  const set = envs.filter((e) => conn?.environments[e.id]?.set).map((e) => e.id);
  const environment = (all && leading(all, set)) ?? set[0] ?? 'production';
  // Connected means an account signed in or a key passed its test (the app answer's state), not settings saved.
  const connected = card.state ? card.state === 'connected' || card.state === 'expired' || card.state === 'refused' : set.length > 0;
  // People connect their own account only where the connection lets them; a team-only one shows its account alone.
  const signsIn = Boolean(kind?.signsIn) && conn?.signIn !== 'team';
  // The team account signed in, but the test call after it failed: shown on its row with Reconnect.
  const failure = testFailure(card);

  type Account = NonNullable<AppData['accounts']>[number];
  // The page's answer lists the team's accounts, the default first; an older answer without them shows the one.
  const accounts: Account[] = data.accounts?.length
    ? data.accounts
    : conn && connected
      ? [{ id: conn.id, name: conn.name, default: true, state: conn.status === 'needs_reconnect' ? 'expired' : 'connected', status: conn.status, statusDetail: conn.statusDetail, mine: data.me.connected, account: data.me.account, pinned: false }]
      : [];

  const signIn = (account: 'self' | 'team', connectionId = conn?.id) => {
    if (!connectionId) return;
    // Opened in the click, before the call that starts the sign-in, so a pop-up blocker lets it through.
    const w = signInWindow.open(card.name, card.logo);
    if (!w) return;
    signedInAs.current = { account, environment };
    start.mutate({ connectionId, environment, account }, { onSuccess: (s) => w.go(s, connectionId), onError: (e) => w.fail(e.message) });
  };

  // The person's own account is a row of Accounts (the final Apps design): Connected as them, or Not signed in.
  const me = { connected: data.me.connected, account: data.me.account, email: session?.user.email };
  const tabs: [string, string][] = [['tools', 'Tools'], ['resources', 'Resources'], ['secrets', 'Secrets'], ['logs', 'Logs'], ['settings', 'Settings']];

  return (
    <PageLayout
      icon={<Logo name={card.name} logo={card.logo} />}
      title={card.name}
      description={`${plural(card.toolsCount, 'tool')}${card.kindLabel ? ` · ${card.kindLabel}` : ''}`}
      breadcrumbs={[{ label: 'Apps', href: '/integrations' }, { label: card.name }]}
      // The Apps menu's tabs and a way back to the catalog, as the app page's frame draws them (Apps (final) group 4).
      backHref="/integrations"
      tabs={<AppsTabs />}
      badge={
        connected ? (
          <Badge variant="outline" className={OK} data-testid="app-status">
            <CircleCheck />
            Connected
          </Badge>
        ) : (
          <Badge variant="outline" data-testid="app-status">
            Not connected
          </Badge>
        )
      }
      contentClassName="flex flex-col gap-4"
    >
      {card.kind === 'plugin' && <PluginUpdatePanel pluginId={card.id.replace(/^plugin:/, '')} name={card.name} />}
      <Section
        title="Accounts"
        description="Calls use the default account unless a step names another. Each person may connect their own."
        flush
        actions={
          several && conn?.mayManage ? (
            <Button size="sm" variant="outline" onClick={() => setAnother(true)} data-testid="app-connect-another">
              <Plus />
              Connect another account
            </Button>
          ) : undefined
        }
      >
        {!conn || (!connected && !signsIn) ? (
          // Connect comes first: an app has no account until someone signs in or a key passes its test. Where each
          // person signs in with their own account, their row shows even before any team account exists.
          <div className="p-4" data-testid="app-not-connected">
            <ListEmpty
              icon={Plug}
              noun="accounts"
              filtered={false}
              description={`${card.name} has no account yet. Connect signs one in; calls stay off until then.`}
              createLabel={card.mayManage ? `Connect ${card.name}` : undefined}
              onCreate={card.mayManage ? () => setConnecting(true) : undefined}
            />
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
                    <AccountState status={a.state === 'expired' || a.state === 'refused' || a.state === 'revoked' ? 'expired' : a.state === 'not_signed_in' ? 'unsigned' : 'connected'} />
                    {a.pinned && accounts.length > 1 && <Badge variant="outline">Your default</Badge>}
                    <span className="text-xs text-muted-foreground">Team account</span>
                  </span>
                }
                description={
                  a.default && failure ? (
                    <span className="text-warning-text" data-testid="app-test-failed">
                      Signed in, but a test call failed: {failure}
                    </span>
                  ) : a.mine ? (
                    `Connected as ${a.account ?? 'you'}`
                  ) : (
                    (a.statusDetail ?? undefined)
                  )
                }
                trailing={
                  conn.mayManage && (a.state === 'expired' || a.state === 'refused' || a.status === 'needs_reconnect' || (a.default && failure)) ? (
                    // Reconnect is the team account signing in again on the app's own page; nothing is typed.
                    <Button size="sm" onClick={() => signIn('team', a.id)} data-testid={a.default ? 'app-reconnect' : `account-reconnect-${a.name}`}>
                      <RefreshCw />
                      Reconnect
                    </Button>
                  ) : conn.mayManage && a.state === 'not_signed_in' && !a.mine ? (
                    // A team account made but never signed in (an earlier window closed, or the app turned off and on).
                    <Button size="sm" onClick={() => signIn('team', a.id)} data-testid="app-sign-in-team">
                      <ExternalLink />
                      Sign in
                    </Button>
                  ) : a.mine && !a.pinned && accounts.length > 1 ? (
                    <LoadingButton
                      size="sm"
                      variant="outline"
                      isLoading={pin.isPending && pin.variables === a.id}
                      onClick={() => pin.mutate(a.id, { onSuccess: () => void app.refetch(), onError: (e) => toast.error('Couldn’t make it your default', { description: e.message }) })}
                      data-testid={`account-pin-${a.name}`}
                    >
                      Make my default
                    </LoadingButton>
                  ) : !a.mine && signsIn && !a.default ? (
                    <Button size="sm" variant="outline" onClick={() => signIn('self', a.id)} data-testid={`account-connect-${a.name}`}>
                      <ExternalLink />
                      Connect my account
                    </Button>
                  ) : undefined
                }
              />
            ))}
            {signsIn && (
              <Row
                wrap
                leading={<Logo name={card.name} logo={card.logo} />}
                title={
                  <span className="flex flex-wrap items-center gap-2" data-testid="app-me">
                    {me.connected ? `Connected as ${me.account ?? 'you'}` : (me.email ?? 'Your account')}
                    <AccountState status={me.connected ? 'connected' : 'unsigned'} />
                    <span className="text-xs text-muted-foreground">Your account</span>
                  </span>
                }
                description={me.connected ? undefined : 'Connect my account to use it'}
                trailing={
                  me.connected ? (
                    <LoadingButton
                      size="sm"
                      variant="ghost"
                      isLoading={signOut.isPending}
                      onClick={() => signOut.mutate({ connectionId: conn.id, environment }, { onError: (e) => toast.error('Couldn’t disconnect', { description: e.message }) })}
                      data-testid="app-disconnect"
                    >
                      Disconnect
                    </LoadingButton>
                  ) : (
                    <LoadingButton size="sm" isLoading={start.isPending} onClick={() => signIn('self')} data-testid="app-connect-me">
                      <ExternalLink />
                      Connect my account
                    </LoadingButton>
                  )
                }
              />
            )}
          </Rows>
        )}
      </Section>
      <Tabs defaultValue="tools">
        {/* The five tabs are wider than a phone: the row scrolls sideways instead of clipping the last one. */}
        <div className="max-w-full overflow-x-auto [scrollbar-width:thin]" data-testid="app-tabs-row">
        <TabsList className="w-max">
          {tabs.map(([value, label]) => (
            <TabsTrigger key={value} value={value} data-testid={`app-tab-${value}`}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
        </div>
        <TabsContent value="tools">
          <ToolsTab app={data} />
        </TabsContent>
        <TabsContent value="resources">
          <ResourcesTab app={data} />
        </TabsContent>
        <TabsContent value="secrets">
          <SecretsTab conn={conn} envs={envs} onReconnect={() => setDialog({ mode: 'edit' })} />
        </TabsContent>
        <TabsContent value="logs">
          {/* The same call log as Tool calls, fixed to this app's tools. */}
          <div className="flex flex-col gap-2" data-testid="app-logs">
            <ToolCallsView fixed={{ moduleId: card.moduleIds }} totals={false} emptyText={`No call of ${card.name}’s tools yet.`} />
          </div>
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab app={data} kinds={all} onSetUp={(e) => setDialog({ mode: 'edit', environment: e })} />
        </TabsContent>
      </Tabs>
      {dialog && conn && (
        <ConnectSystemDialog
          // A plugin's environment is set up with the plugin's own fields (its sign-in address, the team's own app).
          target={card.kind === 'plugin' && card.plugin ? { kind: 'plugin', card } : { kind: 'connection', connectionId: conn.id }}
          mode={dialog.mode}
          environment={dialog.environment}
          open
          onOpenChange={(o) => !o && (setDialog(null), void app.refetch())}
        />
      )}
      {another && card.pluginId && all && connectsInWindow(card, all) ? (
        <ConnectWindow card={card} kinds={all} another open onOpenChange={(o) => !o && (setAnother(false), void app.refetch())} />
      ) : another && card.pluginId ? (
        <AnotherAccountDialog
          app={card.name}
          pluginId={card.pluginId}
          signInOptions={card.plugin?.signIn ?? []}
          onClose={() => setAnother(false)}
          onMade={() => {
            setAnother(false);
            void app.refetch();
          }}
        />
      ) : null}
      {connecting &&
        (all && connectsInWindow(card, all) ? (
          <ConnectWindow card={card} kinds={all} open onOpenChange={(o) => !o && (setConnecting(false), void app.refetch())} />
        ) : (
          <ConnectSystemDialog
            target={card.kind === 'plugin' && card.plugin ? { kind: 'plugin', card } : conn ? { kind: 'connection', connectionId: conn.id } : { kind: 'module', moduleId: card.moduleIds[0] ?? '', name: card.name }}
            mode="connect"
            open
            onOpenChange={(o) => !o && (setConnecting(false), void app.refetch())}
          />
        ))}
    </PageLayout>
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
  },
];

function ToolsTab({ app }: { app: AppData }) {
  return (
    <div className="flex flex-col gap-2" data-testid="app-tools">
      <div>
        <h3 className="text-sm font-semibold">Installed tools</h3>
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

function SecretsTab({ conn, envs, onReconnect }: { conn: AppData['connection']; envs: { id: string; label: string }[]; onReconnect: () => void }) {
  const rows = envs.flatMap((e) => {
    const env = conn?.environments[e.id];
    if (!env?.set) return [];
    const sealed = Object.entries(env.secrets ?? {}).filter(([, v]) => (v as { set?: boolean })?.set);
    return [
      ...(env.signedIn ? [{ key: `${e.id}-team`, title: `App credential · ${env.platformApp ? 'Ops AI’s app' : 'Your own app'} · ${e.label}`, description: `Signed in${env.signedIn.account ? ` as ${env.signedIn.account}` : ''} · refreshes on use` }] : []),
      ...sealed.map(([name]) => ({ key: `${e.id}-${name}`, title: `${name} · ${e.label}`, description: 'Sealed' })),
    ];
  });
  return (
    <Section title="Secrets" description="The app credential it signs in with, and the secrets its tools use. Values are never shown." flush>
      <Rows testId="app-secrets">
        {rows.length ? (
          rows.map((r) => <Row key={r.key} leading={<KeyRound className="size-4 text-muted-foreground" />} title={r.title} description={r.description} />)
        ) : (
          <Row title="Nothing saved yet" />
        )}
      </Rows>
      {conn?.mayManage && rows.length > 0 && (
        <div className="border-t p-3">
          <Button size="sm" variant="outline" onClick={onReconnect}>
            Replace keys or sign in again
          </Button>
        </div>
      )}
    </Section>
  );
}

function SettingsTab({ app, kinds, onSetUp }: { app: AppData; kinds?: Kinds; onSetUp: (environment: string) => void }) {
  const conn = app.connection;
  const change = useChangeConnection();
  const test = useTestEnvironment();
  const setPlugin = useSetTeamPlugin();
  const kind = kinds?.kinds.find((k) => k.id === conn?.authKind);
  const envs = kinds ? keyed(kinds) : [];
  const [own, setOwn] = React.useState({ clientId: '', clientSecret: '' });
  if (!conn) return null;
  const teamSigned = envs.some((e) => conn.environments[e.id]?.signedIn);
  const everyone = conn.signIn !== 'team';
  const platform = Boolean(conn.environments.production?.platformApp ?? conn.environments.test?.platformApp);
  const flip = (on: boolean) =>
    change.mutate(
      { path: { connection_id: conn.id }, body: { revision: conn.revision, signIn: on ? (teamSigned ? 'person_or_team' : 'person') : 'team', teamBackup: on && teamSigned } },
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
                isLoading={setPlugin.isPending}
                disabled={!own.clientId.trim()}
                onClick={() =>
                  setPlugin.mutate(
                    { path: { plugin_id: app.card.pluginId ?? '' }, body: { enabled: true, environment: 'production', clientId: own.clientId.trim(), ...(own.clientSecret ? { clientSecret: own.clientSecret } : {}) } },
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
      <Section title="Environments" description="Test runs use Test; live runs use Production." flush>
        <Rows testId="app-envs">
          {envs.map((e) => {
            const env = conn.environments[e.id];
            return (
              <Row
                key={e.id}
                wrap
                leading={e.production ? <Globe className="size-4 text-muted-foreground" /> : <FlaskConical className="size-4 text-muted-foreground" />}
                title={
                  <span className="flex flex-wrap items-center gap-2" data-testid={`app-env-${e.id}`} data-status={env?.set ? (env.health?.status ?? 'untested') : 'unset'}>
                    {e.label} <EnvState env={env} />
                  </span>
                }
                description={env?.health?.at ? [`Checked ${relativeTime(env.health.at)}`, env.health.httpStatus, env.health.message].filter(Boolean).join(' · ') : env?.set ? 'Not tested yet' : 'Not set'}
                trailing={
                  conn.mayManage ? (
                    env?.set ? (
                      <span className="flex flex-wrap gap-2">
                        <LoadingButton
                          size="sm"
                          variant="outline"
                          isLoading={test.isPending && test.variables?.environment === e.id}
                          onClick={() => test.mutate({ connectionId: conn.id, environment: e.id }, { onError: (x) => toast.error(`Couldn’t test ${e.label}`, { description: x.message }) })}
                          data-testid={`app-test-${e.id}`}
                        >
                          Test
                        </LoadingButton>
                        {/* Keys and sign-in settings change in the Connect window, one environment at a time (c-617). */}
                        <Button size="sm" variant="ghost" onClick={() => onSetUp(e.id)} data-testid={`app-edit-${e.id}`}>
                          Edit
                        </Button>
                      </span>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => onSetUp(e.id)} data-testid={`app-setup-${e.id}`}>
                        Set up {e.label.toLowerCase()}
                      </Button>
                    )
                  ) : undefined
                }
              >
                {/* A test the service refused (a 400 before anything is sent) says why on the row; nothing else would. */}
                {test.isError && test.variables?.environment === e.id && (
                  <p className="text-sm text-destructive" data-testid={`app-env-error-${e.id}`}>
                    {test.error.message}
                  </p>
                )}
                {env?.certificate && (
                  // A signed client's certificate: its thumbprint and expiry, never its key (the key is never sent back).
                  <p className="flex flex-wrap items-center gap-2 text-sm" data-testid={`app-certificate-${e.id}`}>
                    <span className="text-muted-foreground">Signing certificate</span>
                    <code className="min-w-0 break-all text-xs">{env.certificate.thumbprint}</code>
                    <span>expires {shortDate(env.certificate.notAfter)}</span>
                    {env.certificate.expiresSoon && <Badge variant="outline">Expires soon</Badge>}
                  </p>
                )}
              </Row>
            );
          })}
        </Rows>
      </Section>
      {app.card.pluginId && conn.mayManage && <TurnOffSection name={app.card.name} pluginId={app.card.pluginId} />}
    </div>
  );
}

/**
 * Turn off (group K): stops the app's tools for this team, keeping its accounts and what the team added. The window
 * names every agent and workflow using its tools first, read when it opens; when the service cannot tell, it says so.
 */
function TurnOffSection({ name, pluginId }: { name: string; pluginId: string }) {
  const [open, setOpen] = React.useState(false);
  const users = useAppUsers(open ? pluginId : null);
  const setPlugin = useSetTeamPlugin();
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
              isLoading={setPlugin.isPending}
              disabled={users.isPending || users.isError}
              onClick={() =>
                setPlugin.mutate(
                  { path: { plugin_id: pluginId }, body: { enabled: false, environment: 'production' } },
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
 * Connect another account (c-608): a second org or a second account of the same app, under its own name, with the
 * first's contract; the system's own page then asks to allow access for it. Calls keep the default unless they name it.
 */
function AnotherAccountDialog({ app, pluginId, signInOptions, onClose, onMade }: { app: string; pluginId: string; signInOptions: string[]; onClose: () => void; onMade: (id: string) => void }) {
  const add = useAddAccount();
  const [name, setName] = React.useState('');
  const save = () =>
    add.mutate(
      {
        path: { plugin_id: pluginId },
        // Each person may connect their own account of it too, when the app offers that, as for the first.
        body: { enabled: true, name: name.trim(), environment: 'production', ...(signInOptions.includes('person_or_team') ? { signIn: 'person_or_team' } : {}) },
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
