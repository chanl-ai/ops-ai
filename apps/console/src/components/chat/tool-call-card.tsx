'use client';

import * as React from 'react';
import { CheckCircle2, ChevronDown, Loader2, ShieldCheck, Wrench, XCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ms } from '@/lib/format';
import type { ToolCall } from '@/lib/types/chat';
import { cn } from '@/lib/utils';

const json = (v: unknown) => JSON.stringify(v, null, 2);

/** One tool call: collapsed to a line by default, open to show its input and output. */
export function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = React.useState(false);
  const running = call.status === 'running';
  return (
    <div className="rounded-md border bg-muted/30 text-sm">
      <div className="flex flex-wrap items-center gap-2 px-3 py-1.5">
        <Wrench className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="font-mono text-xs font-medium">{call.name}</span>
        <span className="text-xs text-muted-foreground">{call.server}</span>
        {running ? (
          <span className="inline-flex items-center gap-1 text-xs text-sky-700 dark:text-sky-300">
            <Loader2 className="size-3 animate-spin" /> Running
          </span>
        ) : call.status === 'success' ? (
          <span className="inline-flex items-center gap-1 text-xs text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="size-3" /> {ms(call.durationMs)}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-destructive">
            <XCircle className="size-3" /> Failed
          </span>
        )}
        {call.gated && (
          <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-800 dark:text-amber-300">
            <ShieldCheck className="size-3" /> Drafted for approval · {call.gated.gate}
          </span>
        )}
        <Button variant="ghost" size="sm" className="ml-auto h-6 gap-1 px-2 text-xs" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          Input and output <ChevronDown className={cn('size-3 transition-transform', open && 'rotate-180')} />
        </Button>
      </div>
      {open && (
        <div className="grid gap-2 border-t p-3 md:grid-cols-2">
          <div className="min-w-0 space-y-1">
            <p className="text-xs text-muted-foreground">Input</p>
            <pre className="max-h-48 overflow-auto rounded bg-background p-2 font-mono text-[11px]">{json(call.input)}</pre>
          </div>
          <div className="min-w-0 space-y-1">
            <p className="text-xs text-muted-foreground">Output</p>
            {running ? (
              <p className="text-xs text-muted-foreground">Waiting for the tool to return…</p>
            ) : (
              <pre className="max-h-48 overflow-auto rounded bg-background p-2 font-mono text-[11px]">{json(call.output)}</pre>
            )}
          </div>
          {call.gated && <p className="text-xs text-muted-foreground md:col-span-2">This is a write tool behind a review gate. The call drafted the action; nothing changes in {call.server} until {call.gated.reviewers} approve it.</p>}
        </div>
      )}
    </div>
  );
}
