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
import type { Version } from '@/lib/types/domain';

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
  versions?: Version[];
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
  const [target, setTarget] = React.useState<Version | null>(null);
  const current = versions?.find((v) => v.current);

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
      <ol className="relative flex flex-col gap-3 border-l pl-6" data-testid="version-history">
        {versions.map((v) => (
          <li key={v.version} className="relative">
            <span className={`absolute top-4 -left-[29px] size-2.5 rounded-full border-2 border-background ${v.current ? 'bg-primary' : 'bg-muted-foreground/40'}`} />
            <div className="flex flex-wrap items-start gap-3 rounded-lg border bg-card p-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-semibold">v{v.version}</span>
                  {v.current && <Badge className="h-5 px-1.5 text-[10px]">{currentLabel}</Badge>}
                  <span className="text-sm font-medium">{v.note}</span>
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {v.publishedBy} · {relativeTime(v.publishedAt)}
                </p>
                {v.evalSummary && <EvalSummaryLine summary={v.evalSummary} className="mt-1" />}
                {v.changes.length > 1 && (
                  <ul className="mt-2 list-disc pl-4 text-xs text-muted-foreground">
                    {v.changes.slice(1).map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                )}
              </div>
              {!v.current && (
                <Button variant="outline" size="sm" onClick={() => setTarget(v)}>
                  <RotateCcw className="size-3.5" /> Restore
                </Button>
              )}
            </div>
          </li>
        ))}
      </ol>
      <DialogShell
        open={!!target}
        onOpenChange={(o) => !o && setTarget(null)}
        size="sm"
        title={`Restore v${target?.version}?`}
        description={`Saves a new version, v${(current?.version ?? 0) + 1}, with the ${noun} exactly as it was in v${target?.version}. ${restoreConsequence ?? 'New runs use it immediately.'}`}
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
