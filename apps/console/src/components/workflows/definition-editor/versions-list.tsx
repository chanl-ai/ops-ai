'use client';

import * as React from 'react';
import Link from 'next/link';
import { GitCompare, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { QueryError } from '@/components/shared/query-states';
import { VersionTimeline, VersionTimelineItem } from '@/components/shared/version-history';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useCanBuild } from '@/hooks/me-queries';
import { useDefinitionDiff, useRestoreAsWorkingCopy } from '@/hooks/engine-queries';
import { relativeTime } from '@/lib/format';
import { baseOf, staleSave, staleNote } from '@/lib/save-base';
import type { DefinitionView, DiffSide } from '@/lib/types/engine';

import { ChangesList, changeCount } from './changes-list';
import { StageBadge } from './lifecycle';

type Compare = { from: DiffSide; to: DiffSide; title: string; description: string };

/** One comparison in a sheet: every changed step with each setting old and new, text as a line diff. */
function CompareSheet({ workflowId, compare, onClose }: { workflowId: string; compare: Compare | null; onClose: () => void }) {
  const diff = useDefinitionDiff(workflowId, compare?.from, compare?.to);
  return (
    <DetailSheet open={compare !== null} onOpenChange={(o) => !o && onClose()} title={compare?.title ?? ''} description={compare?.description} testId="definition-compare">
      {diff.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : diff.isError ? (
        <QueryError what="the comparison" error={diff.error} onRetry={() => diff.refetch()} retrying={diff.isFetching} />
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground" data-testid="definition-compare-count">
            {changeCount(diff.data)}
          </p>
          <ChangesList diff={diff.data} detail />
        </div>
      )}
    </DetailSheet>
  );
}

/**
 * The Versions tab: the working copy, then every version newest first with its stage, who made it and when. A version
 * never changes; each can be compared with the live one or restored as the working copy, which goes live only once
 * it is published. Drawn on the timeline the agent page uses for its versions.
 */
export function VersionsList({ view }: { view: DefinitionView }) {
  const id = view.workflowId;
  const canBuild = useCanBuild('workflows');
  const restore = useRestoreAsWorkingCopy(id);
  const [compare, setCompare] = React.useState<Compare | null>(null);
  const [restoring, setRestoring] = React.useState<number | null>(null);
  const live = view.liveVersion;
  const versions = [...view.versions].sort((a, b) => b.version - a.version);

  // A version is compared with the live one; the live one with the version before it.
  const against = (v: number): Compare | null => {
    const other = live !== null && live !== v ? live : versions.find((x) => x.version < v)?.version;
    if (other === undefined) return null;
    // Read from the older to the newer, so "before" is always the earlier version.
    const [from, to] = other < v ? [other, v] : [v, other];
    return { from, to, title: `Version ${from} to version ${to}`, description: live === other ? `Version ${other} is live` : 'The version before it' };
  };

  return (
    <div className="flex flex-col gap-4" data-testid="definition-versions">
      <p className="text-sm text-muted-foreground">A version never changes. Live runs use the live one; a test run can use any.</p>
      {view.review && (
        <Alert data-testid="definition-versions-review">
          <AlertDescription>
            Version {view.review.version} is in review ·{' '}
            <Link className="underline" href={`/work/tasks?review=${encodeURIComponent(view.review.id)}`}>
              Open review
            </Link>
          </AlertDescription>
        </Alert>
      )}
      <VersionTimeline testId="definition-version-list">
        {view.workingCopy && (
          <VersionTimelineItem
            dot="current"
            testId="definition-version-working-copy"
            actions={
              <Button
                variant="outline"
                size="sm"
                onClick={() => setCompare({ from: live ?? versions[0]?.version ?? 1, to: 'working-copy', title: 'Your changes', description: live !== null ? `Against version ${live}, the live one` : 'Against the newest version' })}
                data-testid="definition-compare-working-copy"
              >
                <GitCompare className="size-3.5" /> Compare
              </Button>
            }
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold">Working copy</span>
              <Badge variant="outline">Not published</Badge>
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Saved by {view.workingCopy.updatedBy} · {relativeTime(view.workingCopy.updatedAt)}
            </p>
          </VersionTimelineItem>
        )}
        {versions.map((v) => {
          const cmp = against(v.version);
          return (
            <VersionTimelineItem
              key={v.version}
              dot={v.version === live ? 'success' : 'muted'}
              testId={`definition-version-${v.version}`}
              actions={
                <>
                  {cmp && (
                    <Button variant="outline" size="sm" onClick={() => setCompare(cmp)} data-testid={`definition-compare-${v.version}`}>
                      <GitCompare className="size-3.5" /> Compare
                    </Button>
                  )}
                  {canBuild && (
                    <Button variant="outline" size="sm" onClick={() => setRestoring(v.version)} data-testid={`definition-restore-${v.version}`}>
                      <RotateCcw className="size-3.5" /> Restore
                    </Button>
                  )}
                </>
              }
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold tabular-nums">Version {v.version}</span>
                <StageBadge stage={v.stage} />
              </div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {v.createdBy} · {relativeTime(v.createdAt)}
              </p>
            </VersionTimelineItem>
          );
        })}
      </VersionTimeline>
      {versions.length === 1 && !view.workingCopy && <p className="text-sm text-muted-foreground">Publish to add versions.</p>}
      <CompareSheet workflowId={id} compare={compare} onClose={() => setCompare(null)} />
      <ConfirmActionDialog
        open={restoring !== null}
        onOpenChange={(o) => !o && setRestoring(null)}
        title={`Restore version ${restoring ?? ''}`}
        consequence={`Replaces your working copy with the steps of version ${restoring ?? ''}. Nothing goes live until you publish.`}
        runsNow
        note="Your working copy is replaced; every version stays as it is."
        confirmLabel="Restore"
        isPending={restore.isPending}
        onConfirm={async () => {
          try {
            await restore.mutateAsync({ version: restoring as number, base: baseOf(view.saveBase) });
          } catch (e) {
            const stale = staleSave(e);
            throw stale ? new Error(`${staleNote(stale)} Reload the page to see it, then restore again.`) : e;
          }
          toast.success(`Version ${restoring} is now your working copy`, { action: { label: 'Open canvas', onClick: () => window.location.assign(`/build/workflows/definitions/${encodeURIComponent(id)}`) } });
          setRestoring(null);
        }}
      />
    </div>
  );
}
