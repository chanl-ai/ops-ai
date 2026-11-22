'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { AgentVersion, Version } from '@/lib/types/domain';

/** Workflow versions are published when written; agent versions carry a state and a separate save. */
export type VersionEntry = Version | AgentVersion;

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

/** Asks before a restore, which saves a new version that copies the old one. */
export function RestoreVersionDialog({
  target,
  newest,
  noun,
  restoring,
  restoreConsequence,
  onClose,
  onRestore,
}: {
  target: VersionEntry | null;
  newest: number;
  noun: string;
  restoring: boolean;
  restoreConsequence?: string;
  onClose: () => void;
  onRestore: (version: number) => Promise<unknown>;
}) {
  return (
    <DialogShell
      open={!!target}
      onOpenChange={(o) => !o && onClose()}
      size="sm"
      title={`Restore v${target?.version}?`}
      description={`Saves a new version, v${newest + 1}, with the ${noun} exactly as it was in v${target?.version}. ${restoreConsequence ?? 'New runs use it immediately.'}`}
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={restoring}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={restoring}
            loadingText="Restoring…"
            onClick={async () => {
              if (!target) return;
              await onRestore(target.version);
              onClose();
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
  );
}
