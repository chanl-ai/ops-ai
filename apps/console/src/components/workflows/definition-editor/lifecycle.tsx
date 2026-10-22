'use client';

import * as React from 'react';
import Link from 'next/link';
import { Pause, Play, Rocket } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { DefinitionStage, DefinitionView } from '@/lib/types/engine';
import { cn } from '@/lib/utils';

const STAGE_LABEL: Record<DefinitionStage, string> = { draft: 'Draft', in_review: 'In review', live: 'Live', paused: 'Paused', superseded: 'Superseded' };
const STAGE_TONE: Record<DefinitionStage, string> = {
  draft: 'border-border bg-muted text-muted-foreground',
  in_review: 'border-warning/40 bg-warning/10 text-warning-text',
  live: 'border-success/40 bg-success/10 text-success-text',
  paused: 'border-warning/40 bg-warning/10 text-warning-text',
  superseded: 'border-border text-muted-foreground',
};

export function StageBadge({ stage, testId }: { stage: DefinitionStage; testId?: string }) {
  return (
    <Badge variant="outline" className={cn('font-normal', STAGE_TONE[stage])} data-testid={testId} data-stage={stage}>
      {STAGE_LABEL[stage]}
    </Badge>
  );
}

export type Lifecycle = Pick<DefinitionView, 'version' | 'stage' | 'liveVersion' | 'paused' | 'review' | 'startForm'>;

/**
 * Where the saved versions stand and what can move them: send the latest draft to Reviews, follow an open request,
 * pause or resume live runs. A workflow with unsaved changes is saved first, so what is reviewed is what is stored.
 */
export function LifecycleActions({
  lifecycle,
  dirty,
  onPublish,
  onSetPaused,
  pausing,
}: {
  lifecycle: Lifecycle;
  dirty: boolean;
  onPublish: () => void;
  onSetPaused: (paused: boolean) => Promise<unknown>;
  pausing: boolean;
}) {
  const [confirm, setConfirm] = React.useState<'pause' | 'resume' | null>(null);
  const [error, setError] = React.useState<string>();
  const { version, stage, liveVersion, paused, review } = lifecycle;
  return (
    <>
      <div className="mr-auto flex flex-wrap items-center gap-2 text-sm" data-testid="definition-lifecycle">
        <span className="text-muted-foreground">Version {version}</span>
        <StageBadge stage={stage} testId="definition-stage" />
        {liveVersion !== null && liveVersion !== version && (
          <span className="text-muted-foreground" data-testid="definition-live-version">
            Version {liveVersion} {paused ? 'is paused' : 'is live'}
          </span>
        )}
        {dirty && <span className="text-muted-foreground">· Unsaved changes</span>}
      </div>
      {liveVersion !== null && (
        <Button type="button" variant="outline" onClick={() => setConfirm(paused ? 'resume' : 'pause')} data-testid={paused ? 'definition-resume' : 'definition-pause'}>
          {paused ? <Play /> : <Pause />} {paused ? 'Resume' : 'Pause'}
        </Button>
      )}
      {review ? (
        <Button type="button" variant="outline" asChild data-testid="definition-review-link">
          <Link href={`/reviews?review=${encodeURIComponent(review.id)}`}>Version {review.version} in review</Link>
        </Button>
      ) : (
        stage === 'draft' && (
          <Button type="button" variant="outline" onClick={onPublish} disabled={dirty} title={dirty ? 'Save the version first' : undefined} data-testid="definition-publish">
            <Rocket /> Publish…
          </Button>
        )
      )}
      <DialogShell
        open={confirm !== null}
        onOpenChange={(o) => {
          if (!o) {
            setConfirm(null);
            setError(undefined);
          }
        }}
        size="sm"
        title={confirm === 'pause' ? 'Pause live runs' : 'Resume live runs'}
        description={
          confirm === 'pause'
            ? `New live runs of version ${liveVersion} are refused until you resume. Runs under way finish on their version, and test runs still start.`
            : `New live runs start again on version ${liveVersion}.`
        }
        footer={
          <>
            <Button type="button" variant="outline" onClick={() => setConfirm(null)} disabled={pausing}>
              Cancel
            </Button>
            <LoadingButton
              type="button"
              isLoading={pausing}
              loadingText={confirm === 'pause' ? 'Pausing…' : 'Resuming…'}
              data-testid="definition-pause-confirm"
              onClick={async () => {
                try {
                  await onSetPaused(confirm === 'pause');
                  setConfirm(null);
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Nothing changed');
                }
              }}
            >
              {confirm === 'pause' ? 'Pause' : 'Resume'}
            </LoadingButton>
          </>
        }
      >
        {error ? <p className="text-sm text-destructive">{error}</p> : <p className="text-sm text-muted-foreground">Only the live version is affected; drafts and versions in review are not.</p>}
      </DialogShell>
    </>
  );
}
