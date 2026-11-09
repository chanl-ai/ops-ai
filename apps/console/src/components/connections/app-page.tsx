'use client';

import * as React from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Plug } from 'lucide-react';
import { toast } from 'sonner';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AppLogo } from '@/components/shared/app-logo';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { PageLayout } from '@/components/page-layout';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { ScrollTabsList } from '@/components/shared/setting/scroll-tabs';
import { AccountsTab } from '@/components/connections/app-accounts-tab';
import { AuthConfigsTab } from '@/components/connections/app-auth-configs';
import { ResourcesTab } from '@/components/connections/app-resources';
import { SettingsTab } from '@/components/connections/app-settings-tab';
import { ToolsTab } from '@/components/connections/app-tools-tab';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { ConnectSystemDialog } from '@/components/connections/connect-system-dialog';
import { ConnectWindow, connectsInWindow } from '@/components/connections/connect-window';
import { PluginUpdatePanel } from '@/components/connections/plugin-update-panel';
import { useSignInWindow } from '@/components/connections/sign-in';
import { AppStateBadge } from '@/components/connections/app-state-badge';
import { AddAuthConfigButton, TurnOnButton } from '@/components/connections/app-actions';
import { ToolCallsView } from '@/components/tools/tool-calls-view';
import { useNavAllows } from '@/hooks/me-queries';
import { type SystemCard, useApp, useConnectionKinds, useStartSignIn, useTestAccount } from '@/hooks/systems-queries';
import type { Kinds } from '@/lib/connect-plan';
import { appStateFor } from '@/lib/app-state';
import { plural } from '@/lib/format';
import { TOOL_CALL_LOG } from '@/lib/nav';



/**
 * One app's page: a header with its one Connect, then the tabs. Accounts lists every account that signs in to the app
 * and each person's own sign-in; Tools holds the team's switch per tool; Auth configs how Ops AI signs in; Settings
 * personal accounts, the sign-in and the danger zone. Everything comes from one answer, GET /v1/apps/{id}.
 */
export function AppPageView({ appId }: { appId: string }) {
  const app = useApp(appId);
  const kinds = useConnectionKinds();
  const start = useStartSignIn();
  const router = useRouter();
  const allows = useNavAllows();
  const [setUp, setSetUp] = React.useState(false);
  // The one Connect: a window that asks the auth config, what it leaves open, test or live and team or mine.
  const [connecting, setConnecting] = React.useState(false);
  // ?tab= opens a tab from a link elsewhere (the agent tool picker sends people to Tools).
  const [tab, setTab] = React.useState<string | null>(useSearchParams().get('tab'));
  // The Accounts tab, filtered to one auth config from that config's account count.
  const [config, setConfig] = React.useState<string | null>(null);

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
  // A built-in app runs inside Ops AI: it has no accounts to sign in, so no Accounts, Auth configs or Connect.
  const builtIn = card.kind === 'builtin' || card.kind === 'module';
  const accounts = data.accounts ?? [];
  const configs = (data.authConfigs ?? []).filter((c) => c.type !== 'account');
  // Team setup is the team's view: Connect here is managing the team's apps (the roles grid's connections.manage).
  // Someone who does not hold it signs in as themselves from Connectors (Mine), where the app lets people bring one.
  const ownOnly = !card.mayManage;
  // An app the system does not have installed (removed, or never installed) is shown for the record: nothing connects,
  // signs in or turns it on.
  const removed = card.appState === 'removed' || card.appState === 'not_installed';
  const mayConnect = !removed && card.mayManage;
  const ownSignIn = !removed && Boolean(conn) && card.signIn !== 'team';
  // The header's one next action, from the card's state (lib/app-state.ts), as the card and Settings read it.
  const next = appStateFor(card.appState, Boolean(card.mayManage)).action;

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

  const toolsAdded = data.tools.filter((t) => t.added ?? true).length;
  const mayReadCalls = allows(TOOL_CALL_LOG) === true;
  const tabs: [string, string][] = [
    ...(builtIn ? [] : ([['accounts', `Accounts · ${accounts.length}`]] as [string, string][])),
    ['tools', card.kind === 'plugin' ? `Tools · ${toolsAdded} of ${data.tools.length} added` : 'Tools'],
    // Auth configs are a builder's and an admin's (card.mayManage); the API sends no one else any.
    ...(builtIn || !card.mayManage || !configs.length ? [] : ([['auth', `Auth configs · ${configs.length}`]] as [string, string][])),
    ['resources', 'Resources'],
    // The call log names who called each tool, so it is offered only with its cell (lib/nav.ts TOOL_CALL_LOG).
    ...(mayReadCalls ? ([['logs', 'Logs']] as [string, string][]) : []),
    ['settings', 'Settings'],
  ];
  const showAccounts = (id: string) => (setConfig(id), setTab('accounts'));

  return (
    <PageLayout
      icon={<AppLogo name={card.name} logo={card.logo} className="size-9" />}
      title={card.name}
      description={`${plural(card.toolsCount, 'tool')}${card.kindLabel ? ` · ${card.kindLabel}` : ''}`}
      breadcrumbs={[{ label: 'Connectors', href: '/integrations' }, { label: 'Team setup', href: '/integrations' }, { label: card.name }]}
      backHref="/integrations"
      badge={<AppStateBadge card={card} testId="app-status" />}
      actions={
        builtIn || removed ? undefined : next === 'turn_on' ? (
          <TurnOnButton card={card} onFirstTurnOn={() => setConnecting(true)} testId="app-connect" />
        ) : next === 'add_auth_config' ? (
          <AddAuthConfigButton appId={card.id} variant="default" />
        ) : next === 'ask_admin' ? (
          <AskAnAdmin testId="app-admin-connects" />
        ) : mayConnect ? (
          <Button size="sm" onClick={() => setConnecting(true)} data-testid="app-connect">
            <Plug />
            Connect
          </Button>
        ) : ownSignIn ? (
          <Button size="sm" variant="outline" asChild data-testid="app-own-sign-in">
            <Link href="/integrations/my-accounts">Sign in from Mine</Link>
          </Button>
        ) : (
          <AskAnAdmin testId="app-admin-connects" />
        )
      }
      contentClassName="flex min-w-0 flex-col gap-4"
    >
      {removed && (
        <Alert data-testid="app-removed">
          <AlertTitle>{`${card.name} isn’t installed`}</AlertTitle>
          <AlertDescription>{card.appStateReason}</AlertDescription>
        </Alert>
      )}
      {/* Taking an update is managing the team's apps; the card says when one waits, so nothing asks before then. */}
      {card.plugin?.updateAvailable && card.mayManage && <PluginUpdatePanel appId={card.id} name={card.name} />}
      <Tabs value={tab && tabs.some(([v]) => v === tab) ? tab : tabs[0][0]} onValueChange={(v) => (setTab(v), v !== 'accounts' && setConfig(null))} className="min-w-0">
        {/* Six tabs are wider than a phone: the row scrolls sideways inside its box instead of clipping the last. */}
        <ScrollTabsList tabs={tabs.map(([value, label]) => ({ value, label }))} testId="app-tabs-row" triggerTestId={(v) => `app-tab-${v}`} />
        {!builtIn && (
          <TabsContent value="accounts" className="flex flex-col gap-4">
            <AccountsTab app={data} config={config} onConnect={mayConnect ? () => setConnecting(true) : undefined} onSignIn={signIn} />
          </TabsContent>
        )}
        <TabsContent value="tools">
          <ToolsTab app={data} />
        </TabsContent>
        {!builtIn && card.mayManage && configs.length > 0 && (
          <TabsContent value="auth">
            <AuthConfigsTab app={data} onShowAccounts={showAccounts} />
          </TabsContent>
        )}
        <TabsContent value="resources">
          <ResourcesTab appName={data.card.name} pluginId={data.card.pluginId} onConnect={mayConnect ? () => setConnecting(true) : undefined} />
        </TabsContent>
        <TabsContent value="logs">
          {/* The same call log as Tool calls, fixed to this app's tools. */}
          <div className="flex flex-col gap-2" data-testid="app-logs">
            <ToolCallsView fixed={{ moduleId: card.moduleIds }} totals={false} emptyText={`No call of ${card.name}’s tools yet.`} />
          </div>
        </TabsContent>
        <TabsContent value="settings">
          <SettingsTab app={data} kinds={all} onSetUp={() => setSetUp(true)} onTurnOn={() => setConnecting(true)} onDeleted={() => router.push('/integrations')} />
        </TabsContent>
      </Tabs>
      {setUp && conn && (
        <ConnectSystemDialog
          // A plugin's account is set up with the plugin's own fields (its sign-in address, the team's own app).
          target={card.kind === 'plugin' && card.plugin ? { kind: 'plugin', card } : { kind: 'account', account: { appId, accountId: conn.id } }}
          mode="edit"
          open
          onOpenChange={(o) => !o && (setSetUp(false), void app.refetch())}
        />
      )}
      {connecting &&
        (all && connectsInWindow(card, all) ? (
          <ConnectWindow
            card={card}
            kinds={all}
            another={Boolean(card.connectionId)}
            personal={ownOnly}
            taken={accounts.map((a) => a.name)}
            open
            onOpenChange={(o) => !o && (setConnecting(false), void app.refetch())}
          />
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

