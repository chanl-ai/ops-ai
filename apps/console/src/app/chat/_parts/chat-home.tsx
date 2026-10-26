'use client';

import * as React from 'react';
import Link from 'next/link';
import { Bot } from 'lucide-react';

import { Suggestion } from '@/components/ai-elements/suggestion';
import { Composer } from '@/components/chat/composer';
import { useCollapsedSidebar } from '@/components/shared/collapsed-sidebar';
import { RecordCard } from '@/components/chat/record-cards';
import { QueryError } from '@/components/shared/query-states';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useChatAgents, useDefaultAgent } from '@/hooks/chat-queries';
import { useReviews } from '@/hooks/queries';
import type { ChatAttachment } from '@/lib/types/chat';

/** The four ways to begin, each sent as the first message (c-469); the Ops Assistant answers them with cards. */
const STARTS = [
  { id: 'needs', label: 'What needs me today', detail: 'Your Human Tasks, oldest first', text: 'What needs me today?' },
  { id: 'case', label: 'Find a case', detail: 'By customer, subject or status', text: 'Find my open cases' },
  { id: 'start', label: 'Start a workflow', detail: 'From its start form', text: 'Which workflows can I start?' },
  { id: 'run', label: 'What happened to a run', detail: 'Its steps so far', text: 'What happened to my latest run?' },
];

function greeting(now = new Date()): string {
  const h = now.getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

/**
 * Chat's home (c-469), where a person lands after signing in: the composer, four suggested starts and, under Needs
 * you, the first Human Task assigned to them as its card, or how many are open in their team when none is. Laid out as Focus (owner, 2026-10-22): while the home is
 * open the console sidebar folds to its icon rail, and it is put back as it was when the person leaves. A team with no
 * default agent starts on its Ops Assistant, which the first message creates; the header's picker chooses another agent.
 */
export function ChatHome({
  agents,
  me,
  initialAgentId,
  header,
  creating,
  onStart,
}: {
  agents: ReturnType<typeof useChatAgents>;
  me?: string;
  initialAgentId?: string;
  /** The rail button and title, drawn by the workspace. */
  header: React.ReactNode;
  creating: boolean;
  /** `agentId` undefined starts on the team's default, made on the first chat when the team has none. */
  onStart: (agentId: string | undefined, kbIds: string[], text: string, attachments: ChatAttachment[]) => void;
}) {
  useCollapsedSidebar();

  const list = agents.data ?? [];
  const defaultId = useDefaultAgent().data?.agentId;
  const [picked, setPicked] = React.useState<string | undefined>(initialAgentId);
  const agent = list.find((a) => a.id === (picked ?? defaultId));
  const needs = useReviews({ view: 'mine', page: 1, pageSize: 1 });
  const waiting = needs.data?.data[0];
  // Nothing assigned to the person still leaves the team's open tasks, which an approver decides: say how many.
  const open = useReviews({ view: 'open', page: 1, pageSize: 1 });
  const openCount = open.data?.pagination.total ?? 0;
  const begin = (text: string, attachments: ChatAttachment[] = []) => onStart(agent?.id, agent?.defaultKbIds ?? [], text, attachments);

  return (
    <>
      <header className="flex min-h-12 items-center gap-2 border-b px-3 py-2">
        {header}
        {list.length > 0 && (
          <div className="ml-auto">
            <Select value={agent?.id ?? ''} onValueChange={setPicked}>
              <SelectTrigger size="sm" className="w-auto max-w-56" aria-label="Agent" data-testid="home-agent">
                <Bot className="size-4 text-muted-foreground" />
                <SelectValue placeholder="Ops Assistant" />
              </SelectTrigger>
              <SelectContent align="end">
                {list.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    {a.name}
                    {a.id === defaultId && <span className="text-muted-foreground"> · Default</span>}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </header>
      {agents.isError ? (
        <div className="p-6">
          <QueryError what="agents" onRetry={() => agents.refetch()} error={agents.error} retrying={agents.isFetching} />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" data-testid="home-start">
          <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-4 py-8">
            <div className="flex flex-col gap-1 text-center">
              <h1 className="text-2xl font-semibold tracking-tight">{me ? `${greeting()}, ${me.split(' ')[0]}` : greeting()}</h1>
              <p className="text-sm text-muted-foreground">Ask {agent?.name ?? 'Ops Assistant'} anything, start a workflow, or pick up a task.</p>
            </div>
            <Composer autoFocus placeholder="Ask, find a case or customer, or start a workflow…" streaming={creating} onStop={() => undefined} onSend={(text, files) => begin(text, files)} />
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" data-testid="home-starts">
              {STARTS.map((s) => (
                <Suggestion key={s.id} suggestion={s.text} onClick={() => begin(s.text)} disabled={creating} className="h-auto justify-start rounded-lg px-3 py-2 text-left" data-testid={`home-start-${s.id}`}>
                  <span className="flex min-w-0 flex-col">
                    <span className="font-medium">{s.label}</span>
                    <span className="text-xs font-normal text-muted-foreground">{s.detail}</span>
                  </span>
                </Suggestion>
              ))}
            </div>
            <section className="flex flex-col gap-2" aria-labelledby="needs-you" data-testid="home-needs-you">
              <h2 id="needs-you" className="text-sm font-medium text-muted-foreground">
                Needs you
              </h2>
              {needs.isPending ? (
                <Skeleton className="h-32 w-full rounded-xl" />
              ) : waiting ? (
                <RecordCard cardRef={{ type: 'task', id: waiting.id, view: waiting }} onActed={() => void needs.refetch()} />
              ) : (
                <p className="text-sm text-muted-foreground" data-testid="home-needs-none">
                  Nothing is assigned to you.
                  {openCount > 0 && (
                    <>
                      {' '}
                      <Link href="/reviews" className="font-medium text-foreground underline-offset-4 hover:underline" data-testid="home-needs-open">
                        {openCount === 1 ? '1 task is open in your team' : `${openCount} tasks are open in your team`}
                      </Link>
                      .
                    </>
                  )}
                </p>
              )}
            </section>
          </div>
        </div>
      )}
    </>
  );
}
