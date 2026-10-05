'use client';

import Link from 'next/link';
import { Code2, Mail, MessageSquare, Phone } from 'lucide-react';

import { LiveBadge } from '@/components/status-badges';
import { count, initials, pct } from '@/lib/format';
import type { Agent, Channel } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

export const CHANNEL_ICON: Record<Channel, typeof Phone> = { voice: Phone, chat: MessageSquare, email: Mail, api: Code2 };

export function ChannelList({ channels }: { channels: Channel[] }) {
  return (
    <span className="flex flex-wrap items-center gap-2">
      {channels.map((ch) => {
        const Icon = CHANNEL_ICON[ch];
        return (
          <span key={ch} className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Icon className="size-3" /> {ch === 'api' ? 'API' : ch[0].toUpperCase() + ch.slice(1)}
          </span>
        );
      })}
    </span>
  );
}

export function AgentAvatar({ name, className }: { name: string; className?: string }) {
  return (
    <div className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg border bg-muted/50 text-sm font-medium text-muted-foreground', className)}>
      {initials(name)}
    </div>
  );
}

/** Grid card adapted from the shared component library's agents preview: identity, model and channels, then four metrics. */
export function AgentCard({ agent }: { agent: Agent }) {
  const draft = agent.status === 'draft';
  const metrics: [string, string][] = [
    ['Tasks · 24h', draft ? '—' : count(agent.tasks24h)],
    ['Auto-resolved', draft ? '—' : pct(agent.autoResolvedRate)],
    ['Tools', String(agent.toolIds.length)],
    ['Collections', String(agent.collections.length)],
  ];
  return (
    <Link
      href={`/agents/${agent.id}`}
      className={cn('flex h-full flex-col rounded-xl border bg-card p-5 transition-shadow hover:shadow-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', draft && 'opacity-70')}
      data-testid={`agent-card-${agent.slug}`}
    >
      <div className="flex items-start gap-3">
        <AgentAvatar name={agent.name} />
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-medium">{agent.name}</h3>
          <p className="line-clamp-1 text-xs text-muted-foreground">{agent.role}</p>
        </div>
        <span className="font-mono text-[11px] text-muted-foreground">v{agent.version}</span>
      </div>
      <div className="mt-4 flex items-center justify-between gap-2">
        <span className="inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] text-muted-foreground">{agent.model}</span>
        <ChannelList channels={agent.channels} />
      </div>
      <div className="min-h-4 flex-1" />
      <div className="flex items-center justify-between gap-2 border-t pt-4">
        <div className="flex items-center gap-4">
          {metrics.map(([l, v]) => (
            <div key={l}>
              <span className="text-[10px] tracking-wider text-muted-foreground uppercase">{l}</span>
              <p className="text-base font-semibold tabular-nums">{v}</p>
            </div>
          ))}
        </div>
        <LiveBadge status={agent.status} />
      </div>
    </Link>
  );
}
