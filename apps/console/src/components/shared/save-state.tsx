'use client';

import * as React from 'react';
import { AlertTriangle, Check, Loader2, RotateCcw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { type Gate, newGate, type SaveStatus, settle } from '@/lib/save-state-gate';
import { cn } from '@/lib/utils';

export type { SaveStatus };

/** The state to show: follows `want`, but never flashes Saving… for a quick save (lib/save-state-gate.ts). */
export function useSettledStatus(want: SaveStatus): SaveStatus {
  const gate = React.useRef<Gate>(newGate(want));
  const [, tick] = React.useState(0);
  const { shown, wakeAt } = settle(gate.current, want, Date.now());
  React.useEffect(() => {
    if (wakeAt === null) return;
    const t = setTimeout(() => tick((n) => n + 1), Math.max(0, wakeAt - Date.now()));
    return () => clearTimeout(t);
  });
  return shown;
}

const LABEL: Record<SaveStatus, string> = { saved: 'Saved', unsaved: 'Unsaved', saving: 'Saving…', failed: 'Not saved', stale: 'Not saved' };

/**
 * The one save status in a record page's header: Saved, Unsaved, Saving… or Not saved (with Retry when it can).
 * A fixed width so the buttons after it do not move when the word changes.
 */
export function SaveState({ status, detail, onRetry, className }: { status: SaveStatus; detail?: string | null; onRetry?: () => void; className?: string }) {
  const shown = useSettledStatus(status);
  const bad = shown === 'failed' || shown === 'stale';
  return (
    <span
      role="status"
      data-testid="save-state"
      data-state={shown}
      title={detail ?? undefined}
      className={cn('inline-flex h-9 w-28 shrink-0 sm:w-36 items-center justify-end gap-1.5 whitespace-nowrap text-sm', bad ? 'text-destructive-text' : 'text-muted-foreground', className)}
    >
      {shown === 'saving' ? <Loader2 className="size-3.5 animate-spin" /> : bad ? <AlertTriangle className="size-3.5" /> : shown === 'saved' ? <Check className="size-3.5" /> : null}
      {LABEL[shown]}
      {shown === 'failed' && onRetry && (
        <Button type="button" variant="ghost" size="sm" onClick={onRetry} data-testid="save-state-retry">
          <RotateCcw className="size-3.5" /> Retry
        </Button>
      )}
    </span>
  );
}
