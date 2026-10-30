'use client';

import * as React from 'react';
import { ExternalLink, Plug } from 'lucide-react';

import { CONNECTED_MESSAGE, type ConnectedMessage } from '@/components/connections/sign-in';
import { ChatToolCall } from '@/components/shared/chat-blocks';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useMyConnections } from '@/hooks/connections-queries';
import type { ToolCall } from '@/lib/types/chat';
import type { ConnectionRequired } from '@/lib/types/connections';

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
  return { connectionId: e.details.connectionId, connection: e.details.connection ?? 'This system', reason: e.details.reason ?? 'not_connected', connectUrl: e.details.connectUrl, expiresAt: e.details.expiresAt, message: e.message ?? '' };
}

const WHY: Record<ConnectionRequired['reason'], (name: string) => string> = {
  not_connected: (name) => `This tool acts as you, so ${name} records your name on the change. You connect once for this team.`,
  insufficient_scope: (name) => `Your ${name} sign-in does not allow this yet. Connect again and allow the extra access it asks for.`,
  needs_person: (name) => `This tool must act as a person, so ${name} needs your own account. You connect once for this team.`,
};

/**
 * The `connection-required` part (c-558): a tool call that needs the person's own account, with Connect, which opens
 * the system's sign-in in a window, and Not now. Once the window says the person is connected, the chat sends a
 * follow-up so the agent makes the call again, now as them; the refused call never reached the system, so that call
 * is the first. `onReply` is absent in a read-only conversation, which shows no buttons.
 */
export function ConnectionRequiredCard({ call, need, onReply }: { call: ToolCall; need: ConnectionRequired & { message: string }; onReply?: (text: string) => void }) {
  const mine = useMyConnections();
  const [dismissed, setDismissed] = React.useState(false);
  const [connectedNow, setConnectedNow] = React.useState<string | null>(null);
  const window_ = React.useRef<Window | null>(null);
  const linked = mine.data?.find((m) => m.connectionId === need.connectionId);
  // A scope request is answered only by connecting again, so an existing sign-in does not settle it.
  const connected = connectedNow !== null || (need.reason !== 'insufficient_scope' && Boolean(linked));

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
      Connected{linked?.account ? ` as ${linked.account}` : ''}
    </Badge>
  ) : dismissed ? (
    <Badge variant="outline" data-testid="connection-status">
      Not connected
    </Badge>
  ) : (
    <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning-text" data-testid="connection-status">
      Not connected
    </Badge>
  );

  return (
    <div className="flex flex-col gap-2" data-testid="connection-required" data-connection={need.connectionId} data-state={connected ? 'connected' : dismissed ? 'dismissed' : 'open'}>
      <ChatToolCall name={call.label ?? call.name} state="failed" input={call.input} output={call.output} error={need.message || undefined} detail={call.server} />
      <Alert>
        <Plug />
        <AlertTitle className="flex flex-wrap items-center gap-2">
          {connected ? `${need.connection} is connected` : need.reason === 'insufficient_scope' ? `${need.connection} needs more access to continue` : `${need.connection} needs your account to continue`}
          {status}
        </AlertTitle>
        <AlertDescription>
          <p>{connected ? 'Calls that need your account now act as you.' : WHY[need.reason](need.connection)}</p>
          {!connected && !dismissed && onReply && (
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={connect} disabled={!need.connectUrl} data-testid="connection-connect">
                <ExternalLink />
                {need.reason === 'insufficient_scope' ? `Connect ${need.connection} again` : `Connect ${need.connection}`}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setDismissed(true)} data-testid="connection-not-now">
                Not now
              </Button>
            </div>
          )}
          {!need.connectUrl && !connected && <p className="mt-1">Ask again in the chat for a new link, or connect from Your connections.</p>}
        </AlertDescription>
      </Alert>
    </div>
  );
}
