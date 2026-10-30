'use client';

import * as React from 'react';
import { Bot } from 'lucide-react';

import { Suggestion } from '@/components/ai-elements/suggestion';
import { Composer } from '@/components/chat/composer';
import { QueryError } from '@/components/shared/query-states';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { useChatAgents, useDefaultAgent } from '@/hooks/chat-queries';
import { useOverview } from '@/hooks/queries';
import { hintsFrom } from '@/lib/overview';
import type { ChatAttachment } from '@/lib/types/chat';

/** The four general ways to begin when nothing waits, each sent as the first message (c-469); the Ops Assistant answers them with cards. */
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
 * Chat's home, where a person lands after signing in: the greeting, the composer and up to three hints from their own
 * work, or the four general starts when nothing waits (c-552; the sidebar stays as the person left it). A team with no
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
  const list = agents.data ?? [];
  const defaultId = useDefaultAgent().data?.agentId;
  const [picked, setPicked] = React.useState<string | undefined>(initialAgentId);
  const agent = list.find((a) => a.id === (picked ?? defaultId));
  const overview = useOverview();
  const hints = hintsFrom(overview.data);
  const begin = (text: string, attachments: ChatAttachment[] = []) => onStart(agent?.id, agent?.defaultKbIds ?? [], text, attachments);
  // The agent and its default knowledge bases come from the list, so sending waits for it: a message sent before it
  // arrived started on the team's default agent, whatever ?agent= asked for.
  const busy = creating || agents.isPending;

  return (
    <>
      <header className="flex min-h-12 items-center gap-2 border-b px-3 py-2">
        {header}
        {list.length > 0 && (
          <div className="ml-auto">
            <Select value={agent?.id ?? ''} onValueChange={setPicked}>
              <SelectTrigger size="sm" className="w-auto max-w-56 [&_[data-slot=select-value]]:truncate" aria-label="Agent" data-testid="home-agent">
                <Bot className="size-4 text-muted-foreground" />
                {/* The name alone: the Default mark belongs to the list, and in a narrow header it cut the name short. */}
                <SelectValue placeholder="Ops Assistant">{agent?.name}</SelectValue>
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
            <Composer autoFocus draftKey="new" placeholder="Ask, find a case or customer, or start a workflow…" streaming={busy} onStop={() => undefined} onSend={(text, files) => begin(text, files)} />
            {overview.isPending ? (
              <div className="flex flex-col gap-2" data-testid="home-hints-loading">
                <Skeleton className="h-14 w-full rounded-lg" />
                <Skeleton className="h-14 w-full rounded-lg" />
              </div>
            ) : hints.length ? (
              <div className="flex flex-col gap-2" data-testid="home-hints">
                {hints.map((h) => (
                  <Suggestion key={h.id} suggestion={h.text} onClick={() => begin(h.text)} disabled={busy} className="h-auto justify-start rounded-lg px-3 py-2 text-left" data-testid={`home-hint-${h.id}`}>
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate font-medium">{h.label}</span>
                      <span className="text-xs font-normal text-muted-foreground">{h.detail}</span>
                    </span>
                  </Suggestion>
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" data-testid="home-starts">
                {STARTS.map((s) => (
                  <Suggestion key={s.id} suggestion={s.text} onClick={() => begin(s.text)} disabled={busy} className="h-auto justify-start rounded-lg px-3 py-2 text-left" data-testid={`home-start-${s.id}`}>
                    <span className="flex min-w-0 flex-col">
                      <span className="font-medium">{s.label}</span>
                      <span className="text-xs font-normal text-muted-foreground">{s.detail}</span>
                    </span>
                  </Suggestion>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
