'use client';

import { AlertTriangle, Check, Loader2, RotateCcw } from 'lucide-react';
import { Workflow } from 'lucide-react';

import { RouteTabs } from '@/components/shared/route-tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { relativeTime } from '@/lib/format';
import type { DefinitionView } from '@/lib/types/engine';

import type { SaveState } from './use-working-copy';

/**
 * The tabs of one workflow's editor. Each tab is a route, and each tab page renders its own PageLayout with this
 * header, so the standards check finds PageLayout from every routed page. Runs, Tests and Settings join when their
 * routes exist.
 */
export function workflowHeader(id: string, view: DefinitionView | undefined) {
  const base = `/build/workflows/definitions/${encodeURIComponent(id)}`;
  return {
    icon: Workflow,
    title: view?.name || view?.definition.name || id,
    description: view ? (typeof view.definition.description === 'string' && view.definition.description) || (view.liveVersion !== null ? undefined : 'Not live yet') : undefined,
    backHref: '/build/workflows',
    badge: view && (
      <span className="flex flex-wrap items-center gap-1.5">
        {view.liveVersion !== null && (
          <Badge variant="outline" className="border-success/40 bg-success/10 font-normal text-success-text" data-testid="definition-live-chip">
            {view.paused ? `Paused v${view.liveVersion}` : `Live v${view.liveVersion}`}
          </Badge>
        )}
        {view.review && (
          <Badge variant="outline" className="border-warning/40 bg-warning/10 font-normal text-warning-text">
            In review: version {view.review.version}
          </Badge>
        )}
        {view.workingCopy && !view.review && (
          <Badge variant="outline" className="border-warning/40 bg-warning/10 font-normal text-warning-text" data-testid="definition-unpublished">
            Unpublished changes
          </Badge>
        )}
      </span>
    ),
    tabs: (
      <RouteTabs
        tabs={[
          { href: base, label: 'Canvas', testId: 'workflow-tab-canvas' },
          { href: `${base}/versions`, label: 'Versions', testId: 'workflow-tab-versions' },
        ]}
      />
    ),
  };
}

/** Where the working copy's save stands, in the header: Saving…, Saved, or a failure with Retry. */
export function SaveStateLine({ state, savedAt, error, onRetry }: { state: SaveState; savedAt: string | null; error: string | null; onRetry: () => void }) {
  if (state === 'saving')
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground" data-testid="definition-save-state" data-state={state} role="status">
        <Loader2 className="size-3.5 animate-spin" /> Saving…
      </span>
    );
  if (state === 'failed')
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-destructive-text" data-testid="definition-save-state" data-state={state} role="status" title={error ?? undefined}>
        <AlertTriangle className="size-3.5" /> Couldn’t save
        <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={onRetry} data-testid="definition-save-retry">
          <RotateCcw className="size-3.5" /> Retry
        </Button>
      </span>
    );
  if (state === 'stale')
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-warning-text" data-testid="definition-save-state" data-state={state} role="status">
        <AlertTriangle className="size-3.5" /> Not saved: someone else saved first
      </span>
    );
  if (state === 'unsaved')
    return (
      <span className="text-sm text-muted-foreground" data-testid="definition-save-state" data-state={state} role="status">
        Saving soon…
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground" data-testid="definition-save-state" data-state={state} role="status">
      <Check className="size-3.5" /> {savedAt ? `Saved ${relativeTime(savedAt)}` : 'No changes yet'}
    </span>
  );
}
