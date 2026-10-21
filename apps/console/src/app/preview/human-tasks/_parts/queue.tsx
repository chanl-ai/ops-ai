'use client';

import * as React from 'react';
import { CheckCircle2, CreditCard, Gavel } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { Badge } from '@/components/ui/badge';
import { Item, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item';
import { Kbd } from '@/components/ui/kbd';
import { cn } from '@/lib/utils';

import { cad, dueText, isSoon, type QueueItem } from '../_sample/data';
import type { ReviewQueue } from './use-review-queue';

export const KIND_ICON = { court_order: Gavel, card_dispute: CreditCard } as const;

/** Who the item is about: the people a notice names, or the cardholder. */
const subjects = (item: QueueItem) => item.tasks.map((t) => t.subject).join(', ');
/** What is left to decide, in the kind's own word. */
function remaining(item: QueueItem, queue: ReviewQueue) {
  const left = item.tasks.filter((t) => !queue.decisions[t.id]).length;
  if (item.kind === 'card_dispute') return 'Provisional credit';
  return item.tasks.length === 1 ? 'Hold' : `${left} of ${item.tasks.length} holds left`;
}

function DueText({ iso, className }: { iso: string; className?: string }) {
  return <span className={cn('text-xs tabular-nums whitespace-nowrap', isSoon(iso) ? 'font-medium text-warning-text' : 'text-muted-foreground', className)}>{dueText(iso)}</span>;
}

/** One case or notice: whom it names and the amount at stake first, then which notice or dispute, then when it is due. */
export function QueueRow({ item, queue, index, compact, onOpen }: { item: QueueItem; queue: ReviewQueue; index: number; compact?: boolean; onOpen?: () => void }) {
  const Icon = KIND_ICON[item.kind];
  const active = queue.active?.item.id === item.id;
  const cursor = queue.cursor === index;
  return (
    <Item
      asChild
      size="sm"
      variant={active ? 'muted' : 'default'}
      className={cn('w-full flex-nowrap text-left select-none hover:bg-accent/50', active && 'border-border bg-accent', cursor && !active && 'border-ring/60', compact ? 'items-start px-3 py-2' : 'items-start')}
    >
      <button
        type="button"
        aria-current={active ? 'true' : undefined}
        data-testid={`queue-item-${item.id}`}
        data-cursor={cursor ? 'true' : 'false'}
        onClick={() => {
          queue.setCursor(index);
          queue.openItem(item);
          onOpen?.();
        }}
      >
        <ItemMedia>
          <Icon className="size-4 text-muted-foreground" aria-hidden />
        </ItemMedia>
        <ItemContent className="min-w-0 gap-0.5">
          <div className="flex min-w-0 items-baseline justify-between gap-2">
            <ItemTitle className="min-w-0 truncate">{subjects(item)}</ItemTitle>
            {!compact && <span className="shrink-0 text-sm font-medium tabular-nums">{cad(item.total)}</span>}
          </div>
          {!compact && <ItemDescription className="truncate">{item.title}</ItemDescription>}
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            {compact && <span className="text-xs font-medium tabular-nums">{cad(item.total)}</span>}
            <DueText iso={item.due} />
            {!compact && <Badge variant="outline">{remaining(item, queue)}</Badge>}
          </div>
        </ItemContent>
      </button>
    </Item>
  );
}

export function KeyHints({ className }: { className?: string }) {
  return (
    <p className={cn('hidden items-center gap-1 text-xs text-muted-foreground lg:flex', className)}>
      <Kbd>j</Kbd>
      <Kbd>k</Kbd> to move, <Kbd>Enter</Kbd> to open
    </p>
  );
}

/** The queue as a column: every open item by due time, with the count left and the keys that drive it. */
export function QueueList({ queue, onOpen }: { queue: ReviewQueue; onOpen?: () => void }) {
  return (
    <div className="flex min-h-0 flex-col gap-2" data-testid="queue-list">
      <div className="flex items-center justify-between gap-2 px-1">
        <p className="text-sm font-medium">
          <span className="tabular-nums">{queue.items.length}</span> to decide
          {queue.decidedCount > 0 && <span className="font-normal text-muted-foreground"> · {queue.decidedCount} decided</span>}
        </p>
        <KeyHints />
      </div>
      {queue.items.length ? (
        <ItemGroup className="gap-1">
          {queue.items.map((item, i) => (
            <QueueRow key={item.id} item={item} queue={queue} index={i} onOpen={onOpen} />
          ))}
        </ItemGroup>
      ) : (
        <QueueDone />
      )}
    </div>
  );
}

/** The queue as a strip above one task: each item small, scrolling sideways inside the strip, never the page. */
export function QueueStrip({ queue }: { queue: ReviewQueue }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-testid="queue-strip">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">
          <span className="tabular-nums">{queue.items.length}</span> to decide
          {queue.decidedCount > 0 && <span className="font-normal text-muted-foreground"> · {queue.decidedCount} decided</span>}
        </p>
        <KeyHints />
      </div>
      <div className="min-w-0 overflow-x-auto pb-1">
        <ItemGroup className="flex-row gap-1.5">
          {queue.items.map((item, i) => (
            <div key={item.id} className="w-60 shrink-0">
              <QueueRow item={item} queue={queue} index={i} compact />
            </div>
          ))}
        </ItemGroup>
      </div>
    </div>
  );
}

export function QueueDone() {
  return <EmptyState icon={CheckCircle2} title="Nothing left to decide" description="Every task in your queue is decided. New ones appear here as notices and disputes arrive." testId="queue-done" />;
}
