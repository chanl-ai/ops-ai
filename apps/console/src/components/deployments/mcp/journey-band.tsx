'use client';

import { Check, Copy, PlugZap, SquareTerminal, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { ConnectJourney } from '@/lib/types/connect';
import { cn } from '@/lib/utils';

const STEPS: { key: keyof ConnectJourney; title: string; hint: string; icon: typeof Copy }[] = [
  { key: 'copiedUrl', title: 'Copy the URL', hint: 'From the panel below', icon: Copy },
  { key: 'installedClient', title: 'Install it in a client', hint: 'Claude, Cursor, Copilot or ChatGPT', icon: PlugZap },
  { key: 'firstCall', title: 'See the first call', hint: 'Ask your assistant to run a workflow', icon: SquareTerminal },
];

/**
 * Three milestones while setup is incomplete. State comes from the API; the steps happen in the panel below and
 * in the person's own client, so the band states progress and links nowhere.
 */
export function JourneyBand({ journey, onDismiss }: { journey: ConnectJourney; onDismiss: () => void }) {
  const done = STEPS.filter((s) => journey[s.key]).length;
  return (
    <div className="flex flex-col gap-3 rounded-lg border bg-card p-4" data-testid="connect-journey">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">Get connected</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {done} of {STEPS.length}
        </span>
        <Button variant="ghost" size="icon" className="ml-auto size-7" onClick={onDismiss} aria-label="Dismiss">
          <X className="size-4" />
        </Button>
      </div>
      <ol className="grid gap-2 sm:grid-cols-3">
        {STEPS.map((s, i) => {
          const ok = journey[s.key];
          return (
            <li key={s.key} className={cn('flex items-start gap-3 rounded-md border p-3', ok && 'bg-muted/40')} data-testid={`journey-${s.key}`} data-done={ok}>
              <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-full border text-xs', ok ? 'border-success/40 bg-success/10 text-success-text' : 'text-muted-foreground')}>
                {ok ? <Check className="size-4" /> : i + 1}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{s.title}</span>
                <span className="block text-xs text-muted-foreground">{s.hint}</span>
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** Replaces the band once an assistant has made a call. */
export function ConnectedStrip({ assistants, onDismiss }: { assistants: number; onDismiss: () => void }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-sm" data-testid="connect-connected-strip">
      <Check className="size-4 text-success-text" aria-hidden="true" />
      <span className="font-medium">Connected</span>
      <span className="text-muted-foreground">· {assistants === 1 ? '1 assistant has' : `${assistants} assistants have`} called a workflow</span>
      <Button variant="ghost" size="sm" className="ml-auto h-7 text-muted-foreground" onClick={onDismiss}>
        Dismiss
      </Button>
    </div>
  );
}
