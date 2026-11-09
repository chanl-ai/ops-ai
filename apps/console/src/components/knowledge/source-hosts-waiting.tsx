'use client';

import * as React from 'react';
import { Globe } from 'lucide-react';

import { EgressAddDialog } from '@/components/settings/egress-add-dialog';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useCan } from '@/hooks/me-queries';
import type { Source } from '@/lib/types/knowledge';

/**
 * A source's own site waits for its host to be approved under the account's new-hosts rule, as any new outside
 * address does: nothing is fetched until then, and the source syncs once it is. A person who may manage the allowed
 * hosts approves it here, in the egress list's own form; anyone else is told where an admin decides it.
 */
export function SourceHostsWaiting({ source }: { source: Source }) {
  const canApprove = useCan('secrets_egress', 'manage') === true;
  const [approving, setApproving] = React.useState<string | null>(null);
  if (!source.waitingHosts.length) return null;
  const hosts = source.waitingHosts.map((w) => w.host);
  return (
    <Alert data-testid="source-hosts-waiting">
      <Globe className="size-4" />
      <AlertTitle>Waiting for an admin to approve {hosts.join(' and ')}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-2">
        <p>Nothing is fetched from {hosts.length === 1 ? 'it' : 'them'} until then. The source syncs once approved.</p>
        {canApprove ? (
          <span className="flex flex-wrap gap-2">
            {hosts.map((h) => (
              <Button key={h} size="sm" variant="outline" onClick={() => setApproving(h)} data-testid="source-host-approve">
                Approve {h}
              </Button>
            ))}
          </span>
        ) : (
          <span className="text-xs">An admin approves it in Human Tasks or on the Egress page.</span>
        )}
      </AlertDescription>
      <EgressAddDialog kind={approving ? 'host' : null} preset={approving ?? ''} onOpenChange={(o) => !o && setApproving(null)} />
    </Alert>
  );
}
