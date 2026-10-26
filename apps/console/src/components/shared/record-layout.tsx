'use client';

/**
 * Shared record-surface primitives — the "one RecordLayout both pages render
 * through" from the Customer & Company Record UX spec (§05 consistency
 * contract). Customer and Company are the same layout; only the DATA differs.
 *
 *   RecordLayout   — header (via PageLayout) + [320px rail · 1fr main] grid
 *   AttributeCard  — a rail card: title (+ optional edit/settings action) over
 *                    FieldRow rows (Identity, Firmographics, Attributes …)
 *   RecordStatRow  — the 3-tile stat row that sits above the tabbed main
 *
 * The record HEADER is the shared PageLayout (back-icon · name · sub-line ·
 * badge slot · actions) — both record pages already use it, so it is the
 * RecordHeader of the contract. CompanyChip + FieldRow live in their own files.
 *
 * Company adopts these now; the Customer page adopts the same three later so the
 * two records are visibly one family (kills the divergent per-page layouts).
 */

import * as React from 'react';
import type { LucideIcon } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useSidebarFoldsWhenNarrow } from '@/components/shared/collapsed-sidebar';
import { SplitView } from '@/components/shared/setting/split-view';
import { cn } from '@/lib/utils';

/** header (PageLayout) + [rail · main] with a drag handle between them. Rail stacks its cards; below 1024px the columns
 * stack with the main column first, so a phone opens on the record's content (c-500), the rail after it. */
export function RecordLayout({
  rail,
  children,
  className,
}: {
  rail: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  // The main column keeps priority on a 13-inch laptop: the app sidebar folds before the rail and main squeeze.
  useSidebarFoldsWhenNarrow();
  return (
    <div className={className}>
      <SplitView id="record-layout" bare rightFirstWhenStacked defaultLeft={27} leftMin="20" rightMin="40" left={<div className="flex w-full min-w-0 flex-col gap-4">{rail}</div>} right={<div className="min-w-0">{children}</div>} />
    </div>
  );
}

/** A rail card: bordered header (icon · title · optional action) over rows. */
export function AttributeCard({
  title,
  icon: Icon,
  action,
  children,
  className,
  testId,
}: {
  title: React.ReactNode;
  icon?: LucideIcon;
  /** Right-aligned header affordance — e.g. an "Edit" / "Settings" button. */
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <Card className={className} data-testid={testId}>
      <CardHeader className="flex flex-row items-center justify-between gap-2 space-y-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-base font-medium">
          {Icon ? <Icon className="size-4 text-muted-foreground" /> : null}
          {title}
        </CardTitle>
        {action}
      </CardHeader>
      <CardContent className="px-6 pb-4 pt-0">{children}</CardContent>
    </Card>
  );
}

export interface RecordStat {
  label: string;
  value: React.ReactNode;
  testId?: string;
}

/** The 3-tile stat row above the tabbed main (equal-height bordered tiles). */
export function RecordStatRow({
  stats,
  className,
  testId,
}: {
  stats: RecordStat[];
  className?: string;
  testId?: string;
}) {
  return (
    <div className={cn('grid grid-cols-3 gap-3', className)} data-testid={testId}>
      {stats.map((s, i) => (
        <div key={i} className="rounded-lg border bg-card px-3 py-2.5" data-testid={s.testId}>
          <p className="text-xl font-semibold tabular-nums">{s.value}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{s.label}</p>
        </div>
      ))}
    </div>
  );
}
