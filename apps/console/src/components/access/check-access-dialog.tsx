'use client';

import * as React from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';

import { actionLabel, areaLabel, byActionOrder } from '@/components/access/access-words';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useCheckAccess, useRole } from '@/hooks/me-queries';
import type { AccessCheck } from '@/lib/types/settings';

/**
 * Check one action for one person in the team the console acts in (c-150): the services' own check with the
 * workspace's policies, so a separation-of-duties refusal reads as that, not as the grid's yes. Each check is audited.
 */
export function CheckAccessDialog({ open, onOpenChange, personId, personName, teamName }: { open: boolean; onOpenChange: (o: boolean) => void; personId: string; personName: string; teamName: string }) {
  // The Admin role's grid lists every area and action in the catalogue, granted or not.
  const catalogue = useRole('admin');
  const areas = (catalogue.data?.grid ?? []).map((r) => r.area);
  const actions = [...new Set((catalogue.data?.grid ?? []).flatMap((r) => Object.keys(r.actions)))].sort(byActionOrder);
  const [area, setArea] = React.useState('reviews');
  const [action, setAction] = React.useState('decide');
  const [owner, setOwner] = React.useState('');
  const [requestedBy, setRequestedBy] = React.useState('');
  const [answer, setAnswer] = React.useState<AccessCheck | null>(null);
  const check = useCheckAccess();
  React.useEffect(() => {
    if (open) setAnswer(null);
  }, [open]);
  const run = async () => setAnswer(await check.mutateAsync({ personId, area, action, owner: owner.trim() || undefined, requestedBy: requestedBy.trim() || undefined }));
  const pick = (id: string, label: string, value: string, set: (v: string) => void, options: string[], words: (s: string) => string) => (
    <FormField id={id} label={label}>
      <Select value={value} onValueChange={(v) => (set(v), setAnswer(null))}>
        <SelectTrigger id={id} className="w-full bg-card" data-testid={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {words(o)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={`Check ${personName}'s access`}
      description={`In ${teamName}, by the same check the services run, with the workspace's policies. Recorded in the audit log.`}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Done
          </Button>
          <LoadingButton isLoading={check.isPending} onClick={() => void run()} data-testid="check-run">
            Check
          </LoadingButton>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          {pick('check-area', 'Area', area, setArea, areas, areaLabel)}
          {pick('check-action', 'Action', action, setAction, actions, actionLabel)}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="check-owner" label="Record owner" optional hint="For an action allowed on their own records only.">
            <Input id="check-owner" value={owner} onChange={(e) => (setOwner(e.target.value), setAnswer(null))} placeholder="e.g. j.richardson@bank.example" className="bg-card" />
          </FormField>
          <FormField id="check-requested" label="Asked for by" optional hint="For a decision: who asked for it, as the workspace may not let them decide.">
            <Input id="check-requested" value={requestedBy} onChange={(e) => (setRequestedBy(e.target.value), setAnswer(null))} placeholder="e.g. m.okafor@bank.example" className="bg-card" data-testid="check-requested" />
          </FormField>
        </div>
        {check.isError && <p className="text-sm text-destructive">{(check.error as Error).message}</p>}
        {answer &&
          (answer.allowed ? (
            <Alert data-testid="check-result" data-allowed="true">
              <CheckCircle2 className="text-success-text" />
              <AlertTitle>Allowed{answer.scope === 'own' ? ' on their own records' : ''}</AlertTitle>
              <AlertDescription>Granted by {answer.grantedBy.map((r) => `${r.name}${r.via === 'team' ? ' (team)' : ''}`).join(', ') || 'a role'}.</AlertDescription>
            </Alert>
          ) : (
            <Alert variant="destructive" data-testid="check-result" data-allowed="false">
              <XCircle />
              <AlertTitle>Not allowed</AlertTitle>
              <AlertDescription>{answer.refusedBy?.reason}</AlertDescription>
            </Alert>
          ))}
      </div>
    </DialogShell>
  );
}
