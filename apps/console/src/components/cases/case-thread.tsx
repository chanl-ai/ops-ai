'use client';

import { ArrowDownLeft, ArrowUpRight, Paperclip } from 'lucide-react';

import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { dateTime, relativeTime } from '@/lib/format';
import type { CaseEvent, CaseMessage } from '@/lib/types/cases';
import { cn } from '@/lib/utils';

/** The email thread on a case, oldest first, with the agent's summary of each attachment. */
export function CaseConversation({ messages }: { messages: CaseMessage[] }) {
  return (
    <div className="flex flex-col gap-3" data-testid="case-conversation">
      {messages.map((m) => (
        <Card key={m.id} className={cn(m.direction === 'outbound' && 'bg-muted/30')}>
          <CardHeader className="flex flex-row flex-wrap items-baseline justify-between gap-2 space-y-0 pb-2">
            <div className="flex min-w-0 items-center gap-2 text-sm">
              {m.direction === 'inbound' ? <ArrowDownLeft className="size-4 text-sky-600" aria-label="Received" /> : <ArrowUpRight className="size-4 text-emerald-600" aria-label="Sent" />}
              <span className="truncate font-medium">{m.from}</span>
              <span className="truncate text-muted-foreground">to {m.to}</span>
            </div>
            <time className="text-xs text-muted-foreground" dateTime={m.at} title={dateTime(m.at)}>
              {relativeTime(m.at)}
            </time>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-sm font-medium">{m.subject}</p>
            <p className="text-sm whitespace-pre-wrap">{m.body}</p>
            {m.attachments.map((a) => (
              <div key={a.name} className="flex items-start gap-2 rounded-md border bg-card px-3 py-2 text-xs">
                <Paperclip className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="font-medium">
                    {a.name} <span className="font-normal text-muted-foreground">· {a.sizeKb} KB</span>
                  </p>
                  <p className="text-muted-foreground">{a.summary}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Everything that happened to the case, newest first: classification, routing, approvals, edits, replies. */
export function CaseActivity({ events }: { events: CaseEvent[] }) {
  const sorted = [...events].sort((a, b) => b.at.localeCompare(a.at));
  return (
    <Card data-testid="case-activity">
      <CardContent className="pt-6">
        <ol className="relative flex flex-col gap-4 border-l pl-5">
          {sorted.map((e, i) => (
            <li key={`${e.at}-${i}`} className="relative">
              <span className={cn('absolute top-1.5 -left-[25px] size-2 rounded-full', e.kind === 'rejected' ? 'bg-red-500' : e.kind === 'approved' || e.kind === 'executed' ? 'bg-emerald-500' : 'bg-muted-foreground/50')} />
              <p className="text-sm">{e.text}</p>
              <p className="text-xs text-muted-foreground">
                {e.by} · <time dateTime={e.at} title={dateTime(e.at)}>{relativeTime(e.at)}</time>
              </p>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
