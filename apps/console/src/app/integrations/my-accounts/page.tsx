'use client';

import * as React from 'react';
import { Plug, UserRound } from 'lucide-react';
import { toast } from 'sonner';

import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { AppsTabs } from '@/components/connections/apps-tabs';
import { OwnCredentialsForm } from '@/components/connections/own-credentials-form';
import { useSignInWindow } from '@/components/connections/sign-in';
import { DialogShell } from '@/components/shared/dialog-shell';
import { useConnectionKinds, useDisconnect, useMyConnections, useRefreshMine, useStartSignIn } from '@/hooks/connections-queries';
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

/** An OAuth connection the person has not connected: their own sign-in opens in a window, as from the chat. */
function ConnectButton({ c, label = 'Connect' }: { c: MyConnection; label?: string }) {
  const start = useStartSignIn(c.connectionId);
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
        const w = signIn.open(c.connection);
        if (!w) return;
        start.mutate({ environment: c.environment }, { onSuccess: (s) => w.go(s, c.connectionId), onError: (e) => w.fail(e.message) });
      }}
      disabled={start.isPending}
      data-testid={`connect-${c.connectionId}`}
    >
      {label}
    </Button>
  );
}

/** The row's controls by method and state (c-595): a sign-in connects or disconnects; a key adds, replaces or goes. */
function Controls({ c, onEnd, onGive }: { c: MyConnection; onEnd: () => void; onGive: () => void }) {
  const noun = useNoun(c);
  const keyed = c.personFields.length > 0;
  if (!c.connected) {
    return keyed ? (
      <Button size="sm" onClick={onGive} data-testid={`add-own-${c.connectionId}`}>
        Add {noun}
      </Button>
    ) : (
      <ConnectButton c={c} />
    );
  }
  return (
    <div className="flex items-center gap-2">
      {c.refused ? (
        <Badge variant="destructive">{keyed ? 'Refused' : 'Sign-in expired'}</Badge>
      ) : c.connectionStatus === 'needs_reconnect' || c.connectionStatus === 'revoked' ? (
        <Badge variant="destructive">Needs reconnect</Badge>
      ) : (
        <Badge variant="secondary">Connected</Badge>
      )}
      {(c.refused || c.test?.status === 'failed') && !keyed && <ConnectButton c={c} label="Reconnect" />}
      {keyed && (
        <Button variant="outline" size="sm" onClick={onGive} data-testid={`replace-own-${c.connectionId}`}>
          Replace {noun}
        </Button>
      )}
      <Button variant="outline" size="sm" onClick={onEnd} data-testid={`disconnect-${c.connectionId}`}>
        Disconnect
      </Button>
    </div>
  );
}

/** One row's line under its name: the method, then the account or when the key was set, never any part of a secret. */
function describe(c: MyConnection): string {
  if (!c.connected) return [c.method, c.personFields.length ? 'not set' : 'not connected'].join(' · ');
  if (c.refused) {
    const when = c.refusedAt ? ` ${shortDate(c.refusedAt)}` : '';
    const what = c.personFields.length ? `refused${when}` : `sign-in expired${when}`;
    return [c.method, what, c.refusedReason, c.environment].filter(Boolean).join(' · ');
  }
  // Signed in, but the test call after it failed: the account stays connected and says why.
  if (c.test?.status === 'failed') return [`Signed in, but a test call failed: ${c.test.message || 'no reason given'}`, c.environment].join(' · ');
  // A sign-in reads as the My accounts frame: whom it is connected as and since when; a key keeps its method first.
  if (!c.personFields.length) return [`Connected as ${c.account ?? 'an unnamed account'}${c.since ? ` on ${shortDate(c.since)}` : ''}`, c.environment].join(' · ');
  const when = c.since ? `set ${shortDate(c.since)}` : null;
  return [c.method, c.account, when, c.environment].filter(Boolean).join(' · ');
}

/**
 * My accounts (c-558, c-595; in the Apps menu since c-617): every app of the current team that this person may connect
 * as themselves, each with its state and the control its method takes; the list and each state come from the service.
 */
function MyAccountsPage() {
  const { team } = useTeam();
  const mine = useMyConnections(true);
  const disconnect = useDisconnect();
  const [ending, setEnding] = React.useState<MyConnection | null>(null);
  const [giving, setGiving] = React.useState<MyConnection | null>(null);

  const body = mine.isPending ? (
    <Rows>
      {[0, 1].map((i) => (
        <li key={i} className="px-4 py-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="mt-2 h-3 w-64" />
        </li>
      ))}
    </Rows>
  ) : mine.isError ? (
    <QueryError what="your accounts" onRetry={() => void mine.refetch()} retrying={mine.isFetching} error={mine.error} testId="my-connections-error" />
  ) : !mine.data.length ? (
    <EmptyState icon={Plug} title="You haven’t connected any apps yet" description="Connect my account on an app’s page, or from a chat that asks for it." testId="my-connections-empty" />
  ) : (
    <Rows testId="my-connections">
      {mine.data.map((c) => (
        <Row
          key={`${c.connectionId}:${c.environment}`}
          wrap
          leading={<Plug className="size-4 text-muted-foreground" />}
          title={
            <span className="flex flex-wrap items-center gap-2">
              {c.connection}
              {c.environment === 'test' && <Badge variant="outline">Test</Badge>}
            </span>
          }
          description={describe(c)}
          trailing={<Controls c={c} onEnd={() => setEnding(c)} onGive={() => setGiving(c)} />}
        />
      ))}
    </Rows>
  );

  return (
    <PageLayout
      icon={UserRound}
      title="My accounts"
      description={`The apps you connected with your own account in ${team?.name ?? 'this team'}. Tools you run, and agents acting for you, use them.`}
      tabs={<AppsTabs />}
    >
      <Section flush>{body}</Section>
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
            environment={giving.environment}
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
          await disconnect.mutateAsync({ connectionId: ending.connectionId, environment: ending.environment });
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
