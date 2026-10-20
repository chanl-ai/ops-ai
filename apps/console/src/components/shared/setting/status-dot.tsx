'use client';

import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';

export type Health = 'ok' | 'warn' | 'error' | 'idle';

const DOT: Record<Health, string> = { ok: 'bg-success-text', warn: 'bg-warning-text', error: 'bg-destructive', idle: 'bg-muted-foreground/50' };
const WORD: Record<Health, string> = { ok: 'Healthy', warn: 'Needs attention', error: 'Failing', idle: 'Not started' };

/** A coloured dot and a word; hovering shows when it was last checked, relative and exact. */
export function StatusDot({ status, label, at, detail }: { status: Health; label?: string; at?: string; detail?: string }) {
  return (
    <HoverCard openDelay={150}>
      <HoverCardTrigger asChild>
        <span className="inline-flex cursor-default items-center gap-1.5 text-sm" data-testid="status-dot">
          <span aria-hidden="true" className={cn('size-2 rounded-full', DOT[status])} />
          {label ?? WORD[status]}
        </span>
      </HoverCardTrigger>
      <HoverCardContent className="w-64 text-sm" align="start">
        <p className="font-medium">{WORD[status]}</p>
        {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
        <p className="mt-1 text-xs text-muted-foreground">{at ? `Last checked ${relativeTime(at)} · ${new Date(at).toLocaleString('en-CA', { dateStyle: 'medium', timeStyle: 'short' })}` : 'Not checked yet'}</p>
      </HoverCardContent>
    </HoverCard>
  );
}
