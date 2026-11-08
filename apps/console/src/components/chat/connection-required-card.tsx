'use client';

import * as React from 'react';
import { ExternalLink, Plug } from 'lucide-react';

import { CONNECTED_MESSAGE, type ConnectedMessage } from '@/components/connections/sign-in';
import { ChatToolCall } from '@/components/shared/chat-blocks';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { OwnCredentialsForm } from '@/components/connections/own-credentials-form';
import { useMyConnections } from '@/hooks/connections-queries';
import type { ToolCall } from '@/lib/types/chat';
import { actsAs } from '@/lib/failure-words';
import type { ConnectionRequired, ConnectionRequiredReason } from '@/lib/types/connections';

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
    connection: d.connection ?? 'This system',
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
  // A scope request or a refusal is answered only by connecting again, so an existing sign-in does not settle it.
  const connected = connectedNow !== null || (need.reason !== 'insufficient_scope' && need.reason !== 'refused' && Boolean(linked));

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

  const status = connected ? (
    <Badge variant="secondary" data-testid="connection-status">
      {linked?.account ? `Connected as ${linked.account}` : keyed ? `Connected with your ${method}` : 'Connected'}
    </Badge>
  ) : dismissed ? (
    <Badge variant="outline" data-testid="connection-status">
      Not connected
    </Badge>
  ) : need.reason === 'refused' && !keyed ? (
    <Badge variant="destructive" data-testid="connection-status">
      Sign-in expired
    </Badge>
  ) : (
    <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning-text" data-testid="connection-status">
      Not connected
    </Badge>
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
          {!keyed && !need.connectUrl && !connected && <p className="mt-1">Ask again in the chat for a new link, or connect from My accounts under Apps.</p>}
        </AlertDescription>
      </Alert>
    </div>
  );
}
