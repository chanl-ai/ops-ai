'use client';

import * as React from 'react';
import { Globe } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useEgress } from '@/hooks/egress-queries';
import { useCan } from '@/hooks/me-queries';
import { hostOf } from '@/lib/egress';

import { EgressAddDialog } from './egress-add-dialog';

/**
 * A request whose host is not on the egress allowlist is refused before anything is sent (tools-service matches the
 * host exactly). Said beside the URL, with the allowlist's own form opened in place for a person who may add hosts.
 * Nothing shows while the list is loading or the person may not read it.
 */
export function EgressHostNotice({ url }: { url: string }) {
  const host = hostOf(url);
  const list = useEgress();
  const canAdd = useCan('secrets_egress', 'manage') === true;
  const [adding, setAdding] = React.useState(false);
  if (!host || !list.data || list.data.hosts.some((h) => h.host.toLowerCase() === host)) return null;
  return (
    <Alert data-testid="egress-host-notice">
      <Globe />
      <AlertTitle>{host} is not an allowed host</AlertTitle>
      <AlertDescription>
        <span className="flex flex-wrap items-center gap-3">
          Calls to it are refused before anything is sent.
          {canAdd ? (
            <Button type="button" size="sm" variant="outline" onClick={() => setAdding(true)} data-testid="egress-host-add">
              Add allowed host
            </Button>
          ) : (
            <span className="text-xs">A Security admin can add it under Settings, Security, Egress.</span>
          )}
        </span>
      </AlertDescription>
      <EgressAddDialog kind={adding ? 'host' : null} preset={host} onOpenChange={(o) => !o && setAdding(false)} />
    </Alert>
  );
}
