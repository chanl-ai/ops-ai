'use client';

import * as React from 'react';
import Link from 'next/link';
import { ExternalLink, Plug } from 'lucide-react';
import { toast } from 'sonner';

import { CONNECTED_MESSAGE, type ConnectedMessage } from '@/components/connections/sign-in';
import { ChatToolCall } from '@/components/shared/chat-blocks';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AskAnAdmin } from '@/components/connections/ask-an-admin';
import { OwnCredentialsForm } from '@/components/connections/own-credentials-form';
import { useMyConnections, useRefreshMine } from '@/hooks/connections-queries';
import { APP_STATES, labelFor } from '@/lib/app-state';
import { connectCardState } from '@/lib/connect-card-state';
import { AppStateBadge } from '@/components/connections/app-state-badge';
import { usePinDefault } from '@/hooks/systems-queries';
import { useCan } from '@/hooks/me-queries';
import { useTeam } from '@/hooks/use-team';
import type { ToolCall } from '@/lib/types/chat';
import { actsAs } from '@/lib/failure-words';
import type { ConnectionRequired, ConnectionRequiredReason } from '@/lib/types/connections';
import { appPageHref } from '@/lib/app-links';

/**
 * What a tool call refused with `CONNECTION_NOT_LINKED` carries: the gateway's error, as the agent's tool output
 * holds it (`{error: {code, message, details}}`), or null for any other call.
 */
export function connectionRequired(call: ToolCall): (ConnectionRequired & { message: string }) | null {
  if (call.status !== 'failed' || typeof call.output !== 'object' || call.output === null) return null;
  let error = (call.output as { error?: unknown }).error;
  // A refusal relayed whole nests the gateway's error once more.
  if (error && typeof error === 'object' && 'error' in error) error = (error as { error: unknown }).error;
  if (!error || typeof error !== 'object') return null;
  const e = error as { code?: string; message?: string; details?: Partial<ConnectionRequired> };
  if (e.code !== 'CONNECTION_NOT_LINKED' || !e.details?.connectionId) return null;
  const d = e.details;
  return {
    connectionId: e.details.connectionId,
    connection: d.connection ?? 'This app',
    reason: d.reason ?? 'not_connected',
    authKind: d.authKind,
    personFields: d.personFields,
    connectUrl: d.connectUrl,
    expiresAt: d.expiresAt,
    access: d.access === 'write' ? 'write' : 'read',
    app: d.app,
    message: e.message ?? '',
  };
}

type Need = ConnectionRequired & { message: string };
// The app in the person's words: its name ("Salesforce"), else the account's.
const appOf = (need: Need) => need.app ?? need.connection;
const acts = (need: Need) => actsAs({ app: appOf(need), access: need.access });

const WHY: Record<ConnectionRequiredReason, (need: Need, keyed: boolean) => string> = {
  not_connected: (need) => `${acts(need)}. Connect your account once for this team.`,
  insufficient_scope: (need) => `Your ${appOf(need)} sign-in does not allow this yet. Connect again and allow the extra access it asks for.`,
  needs_person: (need) => `${acts(need)}, never as the team. Connect your account once for this team.`,
  no_person: (need) => `${appOf(need)} signs in as each person, and this call ran for nobody. Connect your own account, then ask again.`,
  refused: (need, keyed) => (keyed ? `${appOf(need)} no longer accepts what you gave it. Give it again to go on.` : `Your ${appOf(need)} sign-in has ended. Sign in again to go on.`),
};
// A reason a newer service sends that this console does not know reads as a plain request to connect.
const why = (need: Need, keyed: boolean) => (WHY[need.reason as ConnectionRequiredReason] ?? WHY.not_connected)(need, keyed);

/**
 * The `connection-required` part: a tool call that needs the person's own account, with Connect, which opens
 * the system's sign-in in a window, and Not now. Once the window says the person is connected, the chat sends a
 * follow-up so the agent makes the call again, now as them; the refused call never reached the system, so that call
 * is the first. `onReply` is absent in a read-only conversation, which shows no buttons.
 */
export function ConnectionRequiredCard({ call, need, onReply }: { call: ToolCall; need: ConnectionRequired & { message: string }; onReply?: (text: string) => void }) {
  const mine = useMyConnections(true);
  const [dismissed, setDismissed] = React.useState(false);
  const [connectedNow, setConnectedNow] = React.useState<string | null>(null);
  const window_ = React.useRef<Window | null>(null);
  const linked = mine.data?.find((m) => m.connectionId === need.connectionId && m.connected && !m.refused);
  const offered = mine.data?.find((m) => m.connectionId === need.connectionId);
  // A key, password or token is asked for here; a sign-in at the system opens in its own window.
  const keyed = Boolean(need.personFields?.length);
  const method = linked?.method ?? offered?.method ?? 'key';
  // The refused call's own account decides (lib/connect-card-state.ts); its words come from the one state table.
  const state = connectCardState({ reason: need.reason, linked: Boolean(linked), connectedNow: connectedNow !== null });
  const connected = state === 'connected';

  React.useEffect(() => {
    const onMessage = (e: MessageEvent<ConnectedMessage>) => {
      if (e.origin !== window.location.origin || e.data?.type !== CONNECTED_MESSAGE || e.data.connectionId !== need.connectionId) return;
      if (e.source !== window_.current) return;
      window_.current = null;
      setConnectedNow(e.data.connection);
      void mine.refetch();
      onReply?.(`I connected ${e.data.connection}. Please go ahead.`);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [mine, need.connectionId, onReply]);

  const connect = () => {
    if (!need.connectUrl) return;
    // A window of its own keeps the chat and its draft in place; a phone opens it as a tab.
    window_.current = window.open(need.connectUrl, 'ops-sign-in', 'popup,width=520,height=720');
  };

  const status = dismissed && !connected ? (
    <Badge variant="outline" data-testid="connection-status">
      Not connected
    </Badge>
  ) : connected && linked?.account ? (
    <Badge variant="secondary" data-testid="connection-status" data-state="connected">
      {`${APP_STATES.connected.label} as ${linked.account}`}
    </Badge>
  ) : (
    <AppStateBadge card={{ appState: state }} testId="connection-status" />
  );

  return (
    <div className="flex flex-col gap-2" data-testid="connection-required" data-connection={need.connectionId} data-state={connected ? 'connected' : dismissed ? 'dismissed' : 'open'}>
      <ChatToolCall
        name={call.label ?? call.name}
        state="failed"
        input={call.input}
        output={call.output}
        error={need.message || undefined}
        detail={call.server}
        // The call waits on the person's sign-in; it did not fail.
        badge={
          <Badge variant="outline" className="rounded-full text-xs" data-testid="connection-call-status">
            {need.reason === 'refused' ? 'Sign in again' : 'Needs your sign-in'}
          </Badge>
        }
      />
      <Alert>
        <Plug />
        <AlertTitle className="flex flex-wrap items-center gap-2">
          {connected
            ? `${appOf(need)} is connected`
            : need.reason === 'insufficient_scope'
              ? `${appOf(need)} needs more access to continue`
              : need.reason === 'refused'
                ? keyed
                  ? `${appOf(need)} refused your ${method}`
                  : `${appOf(need)} needs you to sign in again`
                : `${appOf(need)} needs your account to continue`}
          {status}
        </AlertTitle>
        <AlertDescription>
          <p>{connected ? 'Calls that need your account now act as you.' : why(need, keyed)}</p>
          {!connected && !dismissed && onReply && keyed && (
            <OwnCredentialsForm
              connectionId={need.connectionId}
              connection={need.connection}
              authKind={need.authKind}
              personFields={need.personFields ?? []}
              docsUrl={offered?.docsUrl}
              submitLabel={`Connect ${appOf(need)}`}
              onCancel={() => setDismissed(true)}
              onDone={() => {
                setConnectedNow(need.connection);
                void mine.refetch();
                onReply(`I connected ${need.connection}. Please go ahead.`);
              }}
            />
          )}
          {!connected && !dismissed && onReply && !keyed && (
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={connect} disabled={!need.connectUrl} data-testid="connection-connect">
                <ExternalLink />
                {need.reason === 'insufficient_scope' ? `Connect ${appOf(need)} again` : need.reason === 'refused' ? `Sign in to ${appOf(need)} again` : `Connect ${appOf(need)}`}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setDismissed(true)} data-testid="connection-not-now">
                Not now
              </Button>
            </div>
          )}
          {!keyed && !need.connectUrl && !connected && <p className="mt-1">Ask again in the chat for a new link, or connect from Connectors.</p>}
        </AlertDescription>
      </Alert>
    </div>
  );
}

/** What a tool call refused with `APP_OFF_FOR_TEAM` carries: the app the team has off, its id and the team. */
export interface AppOff {
  app: string;
  appId: string;
  teamId?: string;
  message: string;
  /** The app's state for the team, from the refusal's code: off, on with its team account not signed in yet, or on
   * with the one tool the call needs turned off in its catalog. */
  appState: 'off' | 'needs_sign_in' | 'tool_off';
  /** The tool turned off, as the app's Tools tab names it (tool_off only). */
  toolTitle?: string;
  /** The team account was signed in and its sign-in ended (expired, refused or revoked): it is signed in again. */
  again?: boolean;
}

// The refusals for an app the team sets up first, by the app state each means.
const TEAM_FIRST: Record<string, AppOff['appState']> = { APP_OFF_FOR_TEAM: 'off', NOT_SIGNED_IN: 'needs_sign_in', TOOL_NOT_ADDED: 'tool_off' };

/** The app a call found off for the team, from the gateway's error (or the assistant's request_app), or null. */
export function appOffForTeam(call: ToolCall): AppOff | null {
  if (call.status !== 'failed' || typeof call.output !== 'object' || call.output === null) return null;
  let error = (call.output as { error?: unknown }).error;
  if (error && typeof error === 'object' && 'error' in error) error = (error as { error: unknown }).error;
  if (!error || typeof error !== 'object') return null;
  const e = error as { code?: string; message?: string; details?: Partial<AppOff> & { account?: string; connectedEvent?: unknown; toolTitle?: string } };
  // A team account whose sign-in ended names the event its next sign-in reports; any other AUTH_FAILED draws no card.
  const again = e.code === 'AUTH_FAILED' && e.details?.account === 'team' && Boolean(e.details.connectedEvent);
  const appState = again ? 'needs_sign_in' : TEAM_FIRST[e.code ?? ''];
  if (!appState || !e.details?.appId) return null;
  return { app: e.details.app ?? 'This app', appId: e.details.appId, teamId: e.details.teamId, message: e.message ?? '', appState, again, toolTitle: e.details.toolTitle };
}

/**
 * The card for an app the team sets up first: installed but off, or on with its team account not signed in yet. Who
 * manages the team's apps is offered that step on the app's page (Turn on, or Connect the team account); anyone else is
 * shown the team's admins to ask. Its words come from the one state table (lib/app-state.ts). Not now hides the action.
 */
export function AppOffCard({ call, off, readOnly }: { call: ToolCall; off: AppOff; readOnly?: boolean }) {
  const { team } = useTeam();
  const manages = useCan('connections', 'manage') === true;
  const [dismissed, setDismissed] = React.useState(false);
  const teamName = team?.name ?? 'this team';
  const signIn = off.appState === 'needs_sign_in';
  const toolOff = off.appState === 'tool_off';
  const tool = off.toolTitle ?? 'this tool';
  const label = off.appState === 'tool_off' ? 'Tool off' : labelFor(off.appState, manages);
  const title = toolOff
    ? `${off.app}'s ${tool} is turned off for ${teamName}`
    : off.again
    ? `${off.app} needs signing in again`
    : signIn
      ? `${off.app} is on for ${teamName}, but its team account is not signed in`
      : `${off.app} is off for ${teamName}`;
  const said = toolOff
    ? manages
      ? `Turn it on in ${off.app}'s tools; the AI then carries on with this.`
      : 'Only a team admin can turn it on.'
    : off.again
    ? manages
      ? 'Its sign-in ended. Sign it in again; this chat then carries on with it, never with another account.'
      : 'Its sign-in ended. Only a team admin can sign it in again.'
    : manages
    ? signIn
      ? `Connect the team account; its tools then work in chat.`
      : `You can turn it on for ${teamName}; its tools then work in chat.`
    : signIn
      ? 'Only a team admin can connect the team account.'
      : 'Only a team admin can turn it on.';
  return (
    <div className="flex flex-col gap-2" data-testid="app-off-card" data-app={off.appId} data-state={off.again ? 'sign_in_ended' : off.appState}>
      <ChatToolCall
        name={call.label ?? call.name}
        state="failed"
        input={call.input}
        output={call.output}
        error={off.message || undefined}
        detail={call.server}
        badge={
          <Badge variant="outline" className="rounded-full text-xs">
            {label}
          </Badge>
        }
      />
      <Alert>
        <Plug />
        <AlertTitle className="flex flex-wrap items-center gap-2">
          {title}
          <Badge variant="outline">{label}</Badge>
        </AlertTitle>
        <AlertDescription>
          <p>{said}</p>
          {!readOnly && !dismissed && (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {manages ? (
                <Button size="sm" asChild data-testid="app-off-turn-on">
                  <Link href={toolOff ? appPageHref(off.appId, 'tools') : appPageHref(off.appId)}>{toolOff ? `Turn on ${tool}` : off.again ? 'Sign in' : signIn ? 'Connect the team account' : `Turn on ${off.app}`}</Link>
                </Button>
              ) : (
                <AskAnAdmin testId="app-off-ask" />
              )}
              <Button size="sm" variant="outline" onClick={() => setDismissed(true)} data-testid="app-off-not-now">
                Not now
              </Button>
            </div>
          )}
        </AlertDescription>
      </Alert>
    </div>
  );
}

/** What a tool call refused with `ACCOUNT_CHOICE_NEEDED` carries: the app and the person's accounts that fit. */
export interface AccountChoice {
  app: string;
  appId: string;
  accounts: { connectionId: string; name: string; account?: string | null; identity?: { label: string; shown: string; value: string }[] }[];
}

/** The accounts a call asks the person to choose between, from the gateway's error, or null. */
export function accountChoice(call: ToolCall): AccountChoice | null {
  if (call.status !== 'failed' || typeof call.output !== 'object' || call.output === null) return null;
  let error = (call.output as { error?: unknown }).error;
  if (error && typeof error === 'object' && 'error' in error) error = (error as { error: unknown }).error;
  if (!error || typeof error !== 'object') return null;
  const e = error as { code?: string; details?: Partial<AccountChoice> };
  if (e.code !== 'ACCOUNT_CHOICE_NEEDED' || !e.details?.appId || !e.details.accounts?.length) return null;
  return { app: e.details.app ?? 'This app', appId: e.details.appId, accounts: e.details.accounts };
}

/**
 * Two of the person's accounts fit and none is their default: one question, with each account as an answer. The one
 * picked becomes their default for calls that name no account (changed on Connectors), and the chat goes on with it.
 */
export function AccountChoiceCard({ call, choice, onReply }: { call: ToolCall; choice: AccountChoice; onReply?: (text: string) => void }) {
  const pin = usePinDefault();
  const refresh = useRefreshMine();
  const [picked, setPicked] = React.useState<string | null>(null);
  const label = (a: AccountChoice['accounts'][number]) => a.account ?? a.name;
  return (
    <div className="flex flex-col gap-2" data-testid="account-choice-card" data-app={choice.appId}>
      <ChatToolCall
        name={call.label ?? call.name}
        state="failed"
        input={call.input}
        output={call.output}
        detail={call.server}
        badge={
          <Badge variant="outline" className="rounded-full text-xs">
            Which account
          </Badge>
        }
      />
      <Alert>
        <Plug />
        <AlertTitle>{`You have ${choice.accounts.length} ${choice.app} accounts connected`}</AlertTitle>
        <AlertDescription>
          <p>{picked ? `${choice.app} now uses ${picked} unless a call names another. Change it on Connectors.` : `Which ${choice.app} account should this use? Your pick becomes your default; change it on Connectors.`}</p>
          {!picked && onReply && (
            <div className="mt-2 flex flex-wrap gap-2">
              {choice.accounts.map((a) => (
                <Button
                  key={a.connectionId}
                  size="sm"
                  variant="outline"
                  disabled={pin.isPending}
                  data-testid={`account-choice-${a.connectionId}`}
                  onClick={() =>
                    pin.mutate(
                      { appId: choice.appId, accountId: a.connectionId },
                      {
                        onSuccess: () => {
                          setPicked(label(a));
                          refresh();
                          onReply(`Use my ${label(a)} ${choice.app} account. Please go ahead.`);
                        },
                        onError: (e) => toast.error('Couldn’t choose that account', { description: e.message }),
                      },
                    )
                  }
                >
                  <span>{label(a)}</span>
                  {/* Where it points, beside who signed in: two accounts of one person differ only here. */}
                  {(a.identity ?? []).some((e) => e.shown !== label(a)) && (
                    <span className="truncate text-xs text-muted-foreground">
                      {(a.identity ?? [])
                        .filter((e) => e.shown !== label(a))
                        .map((e) => e.shown)
                        .join(' · ')}
                    </span>
                  )}
                </Button>
              ))}
            </div>
          )}
        </AlertDescription>
      </Alert>
    </div>
  );
}
