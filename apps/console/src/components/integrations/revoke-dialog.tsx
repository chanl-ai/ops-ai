'use client';

import * as React from 'react';
import Link from 'next/link';
import { TriangleAlert } from 'lucide-react';

import { SelectedList } from '@/components/shared/bulk';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { plural } from '@/lib/format';
import type { DependantType, RevokeImpact } from '@/lib/types/integrations';

const REASONS = ['No longer needed', 'Access review finding', 'Credential or consent compromised', 'System retired', 'Connected in error'];
const TYPE_LABEL: Record<DependantType, string> = { source: 'Source', tool_module: 'Tool module', mailbox: 'Mailbox' };

/** What stops, in one sentence, from the API's impact counts. */
export function impactSentence(i: RevokeImpact) {
  const parts = [
    i.sources && `${plural(i.sources, 'source')} ${i.sources === 1 ? 'stops' : 'stop'} syncing`,
    i.modules && `${plural(i.modules, 'tool module')} ${i.modules === 1 ? 'fails its' : 'fail their'} calls`,
    i.mailboxes && `${plural(i.mailboxes, 'mailbox', 'mailboxes')} ${i.mailboxes === 1 ? 'stops' : 'stop'} reading mail`,
  ].filter(Boolean);
  return parts.length ? `${parts.join(', ')}.` : 'Nothing uses it, so nothing else stops.';
}

/**
 * Revoke one or several connections, naming everything that stops working. One connection with dependants asks
 * for its name to be typed, as a delete would.
 */
export function RevokeDialog({
  open,
  onOpenChange,
  names,
  impact,
  impactLoading,
  isPending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  names: string[];
  impact?: RevokeImpact;
  impactLoading: boolean;
  isPending: boolean;
  onConfirm: (reason: string) => Promise<unknown>;
}) {
  const [reason, setReason] = React.useState('');
  const [typed, setTyped] = React.useState('');
  React.useEffect(() => {
    if (open) {
      setReason('');
      setTyped('');
    }
  }, [open]);
  const single = names.length === 1;
  const needsName = single && !!impact?.dependants.length;
  const ready = !!reason && !impactLoading && (!needsName || typed === names[0]);

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => !isPending && onOpenChange(o)}
      size="md"
      title={single ? `Revoke “${names[0]}”?` : `Revoke ${names.length} connections?`}
      description="The gateway stops using the credential at once and the consent or key is withdrawn. Reconnecting later needs a new consent or credential."
      data-testid="revoke-dialog"
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton variant="destructive" isLoading={isPending} loadingText="Revoking…" disabled={!ready} onClick={() => onConfirm(reason)}>
            {single ? 'Revoke' : `Revoke ${names.length}`}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-start gap-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
          {impactLoading || !impact ? <Skeleton className="h-4 w-64" /> : <p data-testid="revoke-impact">{impactSentence(impact)}</p>}
        </div>
        {!single && <SelectedList names={names} />}
        {impact && impact.dependants.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-muted-foreground">What stops working</p>
            <ul className="divide-y rounded-md border">
              {impact.dependants.map((d) => (
                <li key={`${d.type}-${d.id}`} className="flex items-start justify-between gap-3 px-3 py-2 text-sm">
                  <span className="min-w-0">
                    <Link href={d.href} className="font-medium hover:underline">
                      {d.name}
                    </Link>
                    <span className="block text-xs text-muted-foreground">{d.stops}</span>
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">{TYPE_LABEL[d.type]}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <FormField id="rv-reason" label="Reason" hint="Recorded in the audit log and shown on the connection.">
          <Select value={reason} onValueChange={setReason}>
            <SelectTrigger id="rv-reason" className="w-full">
              <SelectValue placeholder="Choose a reason" />
            </SelectTrigger>
            <SelectContent>
              {REASONS.map((r) => (
                <SelectItem key={r} value={r}>
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {needsName && (
          <FormField id="rv-name" label={`Type ${names[0]} to confirm`}>
            <Input id="rv-name" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={`e.g. ${names[0]}`} autoComplete="off" />
          </FormField>
        )}
      </div>
    </DialogShell>
  );
}
