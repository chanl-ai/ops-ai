'use client';

import { Workflow } from 'lucide-react';

import { RouteTabs } from '@/components/shared/route-tabs';
import { Badge } from '@/components/ui/badge';
import type { DefinitionView } from '@/lib/types/engine';

/**
 * The tabs of one workflow's editor. Each tab is a route, and each tab page renders its own PageLayout with this
 * header, so the standards check finds PageLayout from every routed page. Runs, Tests and Settings join when their
 * routes exist.
 */
/**
 * `liveChip` false on the canvas, whose lifecycle line already names the live version beside the shown one, so the
 * live state shows once.
 */
export function workflowHeader(id: string, view: DefinitionView | undefined, { liveChip = true }: { liveChip?: boolean } = {}) {
  const base = `/build/workflows/definitions/${encodeURIComponent(id)}`;
  return {
    icon: Workflow,
    title: view?.name || view?.definition.name || id,
    description: view ? (typeof view.definition.description === 'string' && view.definition.description) || (view.liveVersion !== null ? undefined : 'Not live yet') : undefined,
    backHref: '/build/workflows',
    badge: view && (
      <span className="flex flex-wrap items-center gap-1.5">
        {liveChip && view.liveVersion !== null && (
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
          { href: `${base}/batches`, label: 'Batches', testId: 'workflow-tab-batches' },
          { href: `${base}/versions`, label: 'Versions', testId: 'workflow-tab-versions' },
        ]}
      />
    ),
  };
}
