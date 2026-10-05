'use client';

import * as React from 'react';
import { BookOpen, Bot, Check, FlaskConical, ListPlus, Send, UserCheck, Wrench } from 'lucide-react';

import { PermissionNote } from '@/components/run-as/permission-note';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import type { AgentTestTurn } from '@/lib/types/domain';

export interface TestMessage {
  role: 'user' | 'agent' | 'error';
  text: string;
  turn?: AgentTestTurn;
}

/**
 * Sandbox conversation with one agent. Each reply shows the tools it called, what it cited and whether
 * production would have paused the run for review, which is what an ops reviewer needs to trust a change.
 */
export function TestAgentSheet({
  open,
  onOpenChange,
  agentName,
  messages,
  onSend,
  isPending,
  runAs,
  onSaveTurn,
  savingTurn,
  savedTurns = [],
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentName: string;
  messages: TestMessage[];
  onSend: (text: string) => void;
  isPending: boolean;
  /** Who the test runs as (the run-as bar); its permissions apply to every reply. */
  runAs?: React.ReactNode;
  /** Saves the reply at this index (with the message before it) as an eval case. */
  onSaveTurn?: (index: number) => void;
  savingTurn?: boolean;
  /** Indexes already saved, so the button shows it once. */
  savedTurns?: number[];
}) {
  const [draft, setDraft] = React.useState('');
  const endRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, isPending]);

  const send = () => {
    if (!draft.trim() || isPending) return;
    onSend(draft.trim());
    setDraft('');
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex w-full flex-col gap-0 p-0 sm:max-w-lg" data-testid="test-agent-sheet">
        <SheetHeader className="border-b px-5 py-4 pr-12">
          <SheetTitle className="flex items-center gap-2">
            <FlaskConical className="size-4 text-primary" /> Test {agentName}
          </SheetTitle>
          <SheetDescription>Sandbox only. Tools run against test systems and nothing reaches a customer.</SheetDescription>
        </SheetHeader>
        {runAs && <div className="min-w-0 border-b px-5 py-3">{runAs}</div>}
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
          {messages.length === 0 && !isPending && (
            <p className="py-10 text-center text-sm text-muted-foreground">Write what a customer or upstream system would send. Try a request that should pause for review.</p>
          )}
          {messages.map((m, i) =>
            m.role === 'user' ? (
              <div key={i} className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-3.5 py-2 text-sm text-primary-foreground">
                {m.text}
              </div>
            ) : m.role === 'error' ? (
              <p key={i} className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                The test call failed: {m.text}
              </p>
            ) : (
              <div key={i} className="flex max-w-[92%] flex-col gap-2">
                <div className="flex items-start gap-2">
                  <div className="flex size-7 shrink-0 items-center justify-center rounded-full border bg-muted/50">
                    <Bot className="size-3.5 text-muted-foreground" />
                  </div>
                  <div className="rounded-2xl rounded-tl-sm border bg-card px-3.5 py-2 text-sm">{m.text}</div>
                </div>
                {m.turn && (
                  <div className="ml-9 flex flex-col gap-1.5 text-xs">
                    {m.turn.toolCalls.map((t) => (
                      <div key={t.name} className="flex items-center gap-2 rounded-md bg-muted/50 px-2 py-1">
                        <Wrench className="size-3 text-muted-foreground" />
                        <code className="font-mono">{t.name}</code>
                        <span className="truncate text-muted-foreground">→ {t.output}</span>
                      </div>
                    ))}
                    {m.turn.citations.map((c) => (
                      <div key={c.section} className="flex items-center gap-2 text-muted-foreground">
                        <BookOpen className="size-3" /> {c.source} · {c.section}
                      </div>
                    ))}
                    {m.turn.wouldPause && (
                      <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-amber-800 dark:text-amber-300">
                        <UserCheck className="size-3.5 shrink-0" />
                        <span>
                          In production this pauses at <span className="font-medium">{m.turn.wouldPause.gate}</span> for {m.turn.wouldPause.reviewers}.
                        </span>
                      </div>
                    )}
                    <PermissionNote scope={m.turn.permissions} />
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-muted-foreground tabular-nums">
                        {m.turn.tookMs} ms{m.turn.permissions && ` · as ${m.turn.permissions.runAsName}`}
                      </span>
                      {onSaveTurn &&
                        (savedTurns.includes(i) ? (
                          <span className="ml-auto inline-flex items-center gap-1 text-muted-foreground">
                            <Check className="size-3" /> Saved as test
                          </span>
                        ) : (
                          <Button variant="ghost" size="sm" className="ml-auto h-6 px-2 text-xs" disabled={savingTurn} onClick={() => onSaveTurn(i)} data-testid="save-turn-as-test">
                            <ListPlus className="size-3" /> Save as test
                          </Button>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            ),
          )}
          {isPending && (
            <div className="flex items-center gap-2">
              <Skeleton className="size-7 rounded-full" />
              <Skeleton className="h-10 w-56 rounded-2xl" />
            </div>
          )}
          <div ref={endRef} />
        </div>
        <form
          className="flex items-end gap-2 border-t px-5 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <Textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Write a test message…"
            className="max-h-32 min-h-10 resize-none"
            aria-label="Test message"
          />
          <LoadingButton type="submit" size="icon" isLoading={isPending} showSpinner disabled={!draft.trim()} aria-label="Send">
            <Send className="size-4" />
          </LoadingButton>
        </form>
      </SheetContent>
    </Sheet>
  );
}
