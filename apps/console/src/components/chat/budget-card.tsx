'use client';

import * as React from 'react';
import { Gauge } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { BudgetAnswer, BudgetPause } from '@/lib/types/chat';

const WHAT: Record<BudgetPause['limit'], string> = { calls: 'model calls', tokens: 'tokens', cost: 'cost' };

/** The cap as people read it: "200 of 200 model calls" or "5.12 of 5.00 cost". The numbers are the server's. */
const spentText = (p: BudgetPause) => `${p.spent} of ${p.cap} ${WHAT[p.limit]}`;

/**
 * A conversation paused on its budget (c-103): which cap was reached and what was spent, from the server's ledger, with
 * Continue for the conversation's owner and Raise for an admin of its team. The server checks both; this card offers
 * only what the person may do. Once answered it says who continued or raised it.
 */
export function BudgetCard({ pause, canContinue, canRaise, onAnswer }: { pause: BudgetPause; canContinue: boolean; canRaise: boolean; onAnswer: (a: BudgetAnswer) => Promise<unknown> }) {
  const [pending, setPending] = React.useState<'continue' | 'raise' | null>(null);
  const [raising, setRaising] = React.useState(false);
  const [cap, setCap] = React.useState('');
  const [error, setError] = React.useState<string>();
  const send = async (a: BudgetAnswer) => {
    setPending(a.action);
    setError(undefined);
    try {
      await onAnswer({ ...a, pauseId: pause.id });
      setRaising(false);
    } catch (e) {
      if (a.action === 'raise') setError((e as Error).message);
      else toast.error('Couldn’t continue the conversation', { description: (e as Error).message });
    } finally {
      setPending(null);
    }
  };
  if (pause.state !== 'waiting') {
    return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="budget-answered">
        <Gauge className="size-3" /> Budget reached at {spentText(pause)}; {pause.state === 'continued' ? 'continued' : `raised to ${pause.newCap}`} by {pause.answeredBy}.
      </p>
    );
  }
  return (
    <Alert data-testid="budget-card">
      <Gauge className="size-4" />
      <AlertTitle>This conversation reached its budget</AlertTitle>
      <AlertDescription className="flex flex-col gap-3">
        <p>
          It has used {spentText(pause)}. The agent stops here until {canContinue ? 'you continue' : 'its owner continues'}
          {canRaise ? ' or you raise the budget' : ''}.
        </p>
        {(canContinue || canRaise) && (
          <div className="flex flex-wrap gap-2">
            {canContinue && (
              <LoadingButton size="sm" isLoading={pending === 'continue'} loadingText="Continuing…" onClick={() => send({ action: 'continue' })} data-testid="budget-continue">
                Continue
              </LoadingButton>
            )}
            {canRaise && (
              <Button size="sm" variant="outline" onClick={() => (setCap(''), setError(undefined), setRaising(true))} data-testid="budget-raise">
                Raise budget
              </Button>
            )}
          </div>
        )}
      </AlertDescription>
      <DialogShell
        open={raising}
        onOpenChange={setRaising}
        size="sm"
        title="Raise this conversation’s budget"
        description={`For this conversation only. It has used ${spentText(pause)}; the agent’s own caps do not change.`}
        onSubmit={() => {
          const n = Number(cap);
          if (!cap.trim() || !Number.isFinite(n) || n <= 0) return setError(`Enter a new cap for ${WHAT[pause.limit]}.`);
          void send(pause.limit === 'cost' ? { action: 'raise', maxCost: n } : { action: 'raise', maxCalls: Math.floor(n) });
        }}
        footer={
          <>
            <Button type="button" variant="outline" onClick={() => setRaising(false)}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={pending === 'raise'} loadingText="Raising…" data-testid="budget-raise-save">
              Raise and continue
            </LoadingButton>
          </>
        }
      >
        <FormField id="budget-cap" label={pause.limit === 'cost' ? 'New cost cap' : 'New model-call cap'} error={error}>
          <Input id="budget-cap" type="number" min={pause.limit === 'cost' ? 0.01 : 1} step={pause.limit === 'cost' ? 0.01 : 1} value={cap} onChange={(e) => (setCap(e.target.value), setError(undefined))} placeholder={`More than ${pause.spent}`} />
        </FormField>
      </DialogShell>
    </Alert>
  );
}
