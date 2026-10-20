'use client';

import * as React from 'react';
import { History, RotateCcw } from 'lucide-react';

import { EvalSummaryLine } from '@/components/evals/eval-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import { AgentVersionBadge } from '@/components/status-badges';
import type { AgentVersion, Version } from '@/lib/types/domain';

/** Workflow versions are published when written; agent versions carry a state and a separate save. */
export type VersionEntry = Version | AgentVersion;
const savedOf = (v: VersionEntry) => ('savedAt' in v ? { by: v.savedBy, at: v.savedAt } : { by: v.publishedBy, at: v.publishedAt });

const DOT = {
  current: 'bg-primary',
  success: 'bg-success',
  info: 'bg-chart-2',
  destructive: 'bg-destructive',
  muted: 'bg-muted-foreground/40',
} as const;

/** The vertical line every version or decision history hangs on. Rows are `VersionTimelineItem`s. */
export function VersionTimeline({ children, compact, testId }: { children: React.ReactNode; compact?: boolean; testId?: string }) {
  return (
    <ol className={cn('relative flex flex-col border-l', compact ? 'gap-2 pl-4' : 'gap-3 pl-6')} data-testid={testId}>
      {children}
    </ol>
  );
}

/**
 * One entry on a `VersionTimeline`: a dot coloured by state, the entry's own content, and optional actions on the
 * right. `compact` drops the card for short previews that already sit inside a card or sheet.
 */
export function VersionTimelineItem({
  dot = 'muted',
  compact,
  actions,
  children,
  testId,
}: {
  dot?: keyof typeof DOT;
  compact?: boolean;
  actions?: React.ReactNode;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <li className="relative" data-testid={testId}>
      <span className={cn('absolute size-2.5 rounded-full border-2 border-background', compact ? 'top-1.5 -left-[21px]' : 'top-4 -left-[29px]', DOT[dot])} />
      <div className={cn('flex flex-wrap items-start gap-3', !compact && 'rounded-lg border bg-card p-3')}>
        <div className="min-w-0 flex-1">{children}</div>
        {actions && <div className="flex flex-wrap gap-1.5">{actions}</div>}
      </div>
    </li>
  );
}

/**
 * Publish history with restore. A restore publishes a new version that copies the old one, so history
 * only ever grows and the restore itself is auditable.
 */
export function VersionHistory({
  versions,
  isPending,
  isError,
  onRetry,
  onRestore,
  restoring,
  noun,
  currentLabel = 'Live',
  restoreConsequence,
}: {
  versions?: VersionEntry[];
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  onRestore: (version: number) => Promise<unknown>;
  restoring: boolean;
  noun: string;
  /** Badge on the newest version: 'Live' for workflows, 'Current' for agents (workflows pin their own). */
  currentLabel?: string;
  /** What happens after the restore, shown in the confirm. */
  restoreConsequence?: string;
}) {
  const [target, setTarget] = React.useState<VersionEntry | null>(null);
  const newest = Math.max(0, ...(versions ?? []).map((v) => v.version));

  if (isPending)
    return (
      <div className="flex flex-col gap-3">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-20 rounded-lg" />
        ))}
      </div>
    );
  if (isError) return <QueryError what="version history" onRetry={onRetry} />;
  if (!versions?.length) return <EmptyState icon={History} title="Not published yet" description={`The ${noun} has no published versions.`} />;

  return (
    <>
      <VersionTimeline testId="version-history">
        {versions.map((v) => (
          <VersionTimelineItem
            key={v.version}
            dot={v.current ? 'current' : 'muted'}
            actions={
              !v.current && (
                <Button variant="outline" size="sm" onClick={() => setTarget(v)}>
                  <RotateCcw className="size-3.5" /> Restore
                </Button>
              )
            }
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm font-semibold">v{v.version}</span>
              {'state' in v ? <AgentVersionBadge state={v.state} testId={`version-state-v${v.version}`} /> : v.current && <Badge className="h-5 px-1.5 text-[10px]">{currentLabel}</Badge>}
              <span className="text-sm font-medium">{v.note}</span>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {'state' in v ? `Saved by ${savedOf(v).by} · ${relativeTime(savedOf(v).at)}` : `${savedOf(v).by} · ${relativeTime(savedOf(v).at)}`}
              {'state' in v && v.publishedAt && v.state !== 'published' && ` · published ${relativeTime(v.publishedAt)}`}
              {'state' in v && v.state === 'published' && v.publishedBy && ` · published by ${v.publishedBy}`}
            </p>
            {'state' in v && v.decisionReason && <p className="mt-1 text-xs text-muted-foreground">Reviewer: “{v.decisionReason}”</p>}
            {v.evalSummary && <EvalSummaryLine summary={v.evalSummary} className="mt-1" />}
            {v.changes.length > 1 && (
              <ul className="mt-2 list-disc pl-4 text-xs text-muted-foreground">
                {v.changes.slice(1).map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            )}
          </VersionTimelineItem>
        ))}
      </VersionTimeline>
      <DialogShell
        open={!!target}
        onOpenChange={(o) => !o && setTarget(null)}
        size="sm"
        title={`Restore v${target?.version}?`}
        description={`Saves a new version, v${newest + 1}, with the ${noun} exactly as it was in v${target?.version}. ${restoreConsequence ?? 'New runs use it immediately.'}`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setTarget(null)} disabled={restoring}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={restoring}
              loadingText="Restoring…"
              onClick={async () => {
                if (!target) return;
                await onRestore(target.version);
                setTarget(null);
              }}
            >
              Restore v{target?.version}
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">
          v{target?.version}: {target?.note}
        </p>
      </DialogShell>
    </>
  );
}
