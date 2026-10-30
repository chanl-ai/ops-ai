'use client';

import * as React from 'react';
import { notFound } from 'next/navigation';
import { Plug } from 'lucide-react';
import { toast } from 'sonner';

import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useDisconnect, useMyConnections } from '@/hooks/connections-queries';
import { useTeam } from '@/hooks/use-team';
import { shortDate } from '@/lib/format';
import type { MyConnection } from '@/lib/types/connections';
import { personalSignIn } from '@/lib/api';

/** Your connections (c-558): the accounts this person connected for the current team, each to disconnect. */
function YourConnectionsPage() {
  const { team } = useTeam();
  const mine = useMyConnections();
  const disconnect = useDisconnect();
  const [ending, setEnding] = React.useState<MyConnection | null>(null);

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
    <QueryError what="your connections" onRetry={() => void mine.refetch()} retrying={mine.isFetching} error={mine.error} testId="my-connections-error" />
  ) : !mine.data.length ? (
    <EmptyState icon={Plug} title="No connections yet" description="You have no personal connections in this team yet. A tool that needs your account asks you in the chat." testId="my-connections-empty" />
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
          description={[c.account ?? 'Account not named', c.since ? `since ${shortDate(c.since)}` : null].filter(Boolean).join(' · ')}
          trailing={
            <div className="flex items-center gap-2">
              {c.connectionStatus === 'needs_reconnect' || c.connectionStatus === 'revoked' ? <Badge variant="destructive">Needs reconnect</Badge> : <Badge variant="secondary">Connected</Badge>}
              <Button variant="outline" size="sm" onClick={() => setEnding(c)} data-testid={`disconnect-${c.connectionId}`}>
                Disconnect
              </Button>
            </div>
          }
        />
      ))}
    </Rows>
  );

  return (
    <PageLayout icon={Plug} title="Your connections" description={`Accounts you connected for ${team?.name ?? 'this team'}. Other teams keep their own.`}>
      <Section flush>{body}</Section>
      <DeleteDialog
        open={ending !== null}
        onOpenChange={(open) => !open && setEnding(null)}
        entityType="connection"
        entityName={ending?.connection}
        verb="Disconnect"
        testIdPrefix="my-connection"
        description={`Tools that act as you on ${ending?.connection ?? 'this system'} will ask you to connect again. Ops AI also asks ${ending?.connection ?? 'the system'} to end the sign-in.`}
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

/** Not offered until the personal sign-in switch is on (lib/api/index.ts). */
export default function Page() {
  if (!personalSignIn) notFound();
  return <YourConnectionsPage />;
}
