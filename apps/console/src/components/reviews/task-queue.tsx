'use client';

import * as React from 'react';
import { CheckCircle2, FolderOpen } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { isOpen } from '@/components/reviews/review-columns';
import { KIND_LABEL, SlaText } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { Kbd } from '@/components/ui/kbd';
import { Skeleton } from '@/components/ui/skeleton';
import { money } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Review } from '@/lib/types/domain';

export function QueueDone() {
  return <EmptyState icon={CheckCircle2} title="Nothing left to decide" description="Every task in this view is decided. New ones appear here as runs pause for a person." testId="queue-done" />;
}

/**
 * The queue as a column (c-460): the rows in the order the service grouped them, a header wherever the case changes,
 * each row the task's question, who it is about, its amount and when it is due. The service orders and names the
 * cases (`group=case`); this only draws a header where consecutive rows change case. j and k move the cursor, Enter
 * opens the row it is on.
 */
export function TaskQueue({
  rows,
  total,
  activeId,
  loading,
  onOpen,
  onMore,
  loadingMore,
}: {
  rows: Review[];
  /** How many the view holds, loaded or not. */
  total: number;
  activeId: string | null;
  loading: boolean;
  onOpen: (r: Review) => void;
  onMore?: () => void;
  loadingMore?: boolean;
}) {
  const [cursor, setCursor] = React.useState(0);
  const activeIndex = rows.findIndex((r) => r.id === activeId);
  React.useEffect(() => {
    if (activeIndex >= 0) setCursor(activeIndex);
  }, [activeIndex]);
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.closest('[role="dialog"],[role="menu"]'))) return;
      if (!rows.length) return;
      if (e.key === 'j' || e.key === 'k') {
        e.preventDefault();
        // Stops at the last loaded row: the next page comes from Load more, never from a key.
        setCursor((c) => Math.min(rows.length - 1, Math.max(0, c + (e.key === 'j' ? 1 : -1))));
      } else if (e.key === 'Enter' && !t?.closest('button,a,[role="radio"],[role="tab"]')) {
        const r = rows[Math.min(cursor, rows.length - 1)];
        if (!r) return;
        e.preventDefault();
        onOpen(r);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rows, cursor, onOpen]);

  if (loading)
    return (
      <div className="flex flex-col gap-2" data-testid="queue-loading">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-16 w-full rounded-md" />
        ))}
      </div>
    );
  if (!rows.length) return <QueueDone />;
  const unloaded = Math.max(0, total - rows.length);
  return (
    <div className="flex min-h-0 flex-col gap-2" data-testid="queue-list">
      <div className="flex items-center justify-between gap-2 px-1">
        <p className="text-sm font-medium">
          <span className="tabular-nums">{total}</span> to decide
          {unloaded > 0 && <span className="font-normal text-muted-foreground"> · {unloaded} not loaded</span>}
        </p>
        <p className="hidden items-center gap-1 text-xs text-muted-foreground lg:flex">
          <Kbd>j</Kbd>
          <Kbd>k</Kbd> to move, <Kbd>Enter</Kbd> to open
        </p>
      </div>
      <ItemGroup className="gap-1">
        {rows.map((r, i) => {
          const header = r.caseId && r.caseId !== rows[i - 1]?.caseId;
          const active = r.id === activeId;
          return (
            <React.Fragment key={r.id}>
              {header && (
                <div className="flex min-w-0 items-center gap-1.5 px-1 pt-2 text-xs font-medium text-muted-foreground" data-testid={`queue-case-${r.caseId}`}>
                  <FolderOpen className="size-3.5 shrink-0" aria-hidden />
                  <span className="truncate">{r.caseTitle ?? 'Case'}</span>
                </div>
              )}
              <Item
                asChild
                size="sm"
                variant={active ? 'muted' : 'default'}
                className={cn('w-full flex-nowrap items-start text-left select-none hover:bg-accent/50', active && 'border-border bg-accent', cursor === i && !active && 'border-ring/60')}
              >
                <button
                  type="button"
                  aria-current={active ? 'true' : undefined}
                  data-testid={`queue-item-${r.id}`}
                  data-cursor={cursor === i ? 'true' : 'false'}
                  onClick={() => {
                    setCursor(i);
                    onOpen(r);
                  }}
                >
                  <ItemContent className="min-w-0 gap-0.5">
                    <div className="flex min-w-0 items-baseline justify-between gap-2">
                      <ItemTitle className="min-w-0 truncate">{r.title}</ItemTitle>
                      {r.amount != null && <span className="shrink-0 text-sm font-medium tabular-nums">{money(r.amount, r.currency)}</span>}
                    </div>
                    <ItemDescription className="truncate">{[KIND_LABEL[r.kind], r.customer].filter(Boolean).join(' · ')}</ItemDescription>
                    <SlaText minutes={r.slaMinutes} open={isOpen(r)} />
                  </ItemContent>
                </button>
              </Item>
            </React.Fragment>
          );
        })}
      </ItemGroup>
      {onMore && unloaded > 0 && (
        <Button variant="outline" size="sm" onClick={onMore} disabled={loadingMore} data-testid="queue-more">
          Load more
        </Button>
      )}
    </div>
  );
}
