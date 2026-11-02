import { CircleAlert, Clock } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { HostHeldError } from '@/lib/api/held-host';

/**
 * Why a dialog's save did not land, inside the dialog. An address on a host nobody listed is not an error: it waits on
 * the Security team (c-616 S13), so it reads as waiting, and saving again once the host is allowed goes through.
 */
export function SaveProblem({ error }: { error: unknown }) {
  if (!error) return null;
  if (error instanceof HostHeldError)
    return (
      <Alert data-testid="host-held">
        <Clock className="size-4" />
        <AlertTitle>Waiting for Security to allow {error.host}</AlertTitle>
        <AlertDescription>Nothing was saved yet. A Security admin decides in Human Tasks; save again once {error.host} is allowed.</AlertDescription>
      </Alert>
    );
  return (
    <Alert variant="destructive" data-testid="save-problem">
      <CircleAlert className="size-4" />
      <AlertDescription>{error instanceof Error ? error.message : String(error)}</AlertDescription>
    </Alert>
  );
}
