'use client';

import * as React from 'react';
import { ArrowLeft } from 'lucide-react';

import { useCollapsedSidebar } from '@/components/shared/collapsed-sidebar';
import { Button } from '@/components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

import { DecisionPanel } from './decision-panel';
import { EvidencePane } from './evidence-pane';
import { QueueDone, QueueList, QueueStrip } from './queue';
import { useQueueKeys, type ReviewQueue } from './use-review-queue';

type Pane = 'evidence' | 'decide';

// Scroll areas clip rather than hide: a box the document viewer scrolls into view would otherwise scroll an
// overflow-hidden frame and push the page header out of sight.

/**
 * The evidence and the decision side by side from 1024 px: the evidence scrolls in its own column, the decision panel
 * is a column of fixed height beside it. Below 1024 px one shows at a time behind an Evidence and Decide switch, the
 * decision first, and the Decide row stays at the foot of the screen.
 */
function TaskSplit({ queue, wideFrom }: { queue: ReviewQueue; wideFrom: 'lg' | 'xl' }) {
  const [pane, setPane] = React.useState<Pane>('decide');
  const active = queue.active;
  if (!active) return <QueueDone />;
  const wide = wideFrom === 'lg' ? 'lg' : 'xl';
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
      <Tabs value={pane} onValueChange={(v) => setPane(v as Pane)} className={wide === 'lg' ? 'lg:hidden' : 'xl:hidden'}>
        <TabsList className="w-full">
          <TabsTrigger value="decide" data-testid="pane-decide">
            Decide
          </TabsTrigger>
          <TabsTrigger value="evidence" data-testid="pane-evidence">
            Evidence
          </TabsTrigger>
        </TabsList>
      </Tabs>
      <div
        className={cn(
          'grid min-h-0 min-w-0 flex-1 gap-4',
          wide === 'lg' ? 'lg:grid-cols-[minmax(0,1fr)_minmax(30rem,32rem)] lg:grid-rows-[minmax(0,1fr)]' : 'xl:grid-cols-[minmax(0,1fr)_minmax(30rem,32rem)] xl:grid-rows-[minmax(0,1fr)]',
        )}
      >
        <EvidencePane item={active.item} task={active.task} className={cn(pane === 'evidence' ? 'flex' : 'hidden', wide === 'lg' ? 'lg:flex' : 'xl:flex')} />
        <DecisionPanel
          key={active.task.id}
          item={active.item}
          task={active.task}
          queue={queue}
          className={cn(pane === 'decide' ? 'flex' : 'hidden', wide === 'lg' ? 'lg:flex' : 'xl:flex')}
        />
      </div>
    </div>
  );
}

function CollapseNav() {
  useCollapsedSidebar();
  return null;
}

/**
 * Option A, queue and task: the queue is a column on the left and the open task fills the rest, evidence then the
 * decision. The app's navigation folds away while the page is open so the document has room. Below 1280 px the queue
 * and the task take turns.
 */
export function LayoutA({ queue }: { queue: ReviewQueue }) {
  const [view, setView] = React.useState<'queue' | 'task'>('queue');
  const showTask = React.useCallback(() => setView('task'), []);
  useQueueKeys(queue, showTask);
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pb-4 xl:flex-row xl:overflow-clip" data-testid="layout-a">
      <CollapseNav />
      <div className={cn('min-h-0 flex-col xl:flex xl:w-72 xl:shrink-0 xl:overflow-y-auto xl:pr-1', view === 'queue' ? 'flex' : 'hidden')}>
        <QueueList queue={queue} onOpen={showTask} />
      </div>
      <div className={cn('min-h-0 min-w-0 flex-1 flex-col gap-3 xl:flex', view === 'task' ? 'flex' : 'hidden')}>
        <Button variant="ghost" size="sm" className="self-start xl:hidden" onClick={() => setView('queue')} data-testid="back-to-queue">
          <ArrowLeft /> Queue
        </Button>
        <TaskSplit queue={queue} wideFrom="xl" />
      </div>
    </div>
  );
}

/**
 * Option B, one task at a time: the queue shrinks to a strip across the top and the task below it has the full width,
 * evidence and decision side by side.
 */
export function LayoutB({ queue }: { queue: ReviewQueue }) {
  useQueueKeys(queue);
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pb-4 lg:overflow-clip" data-testid="layout-b">
      <QueueStrip queue={queue} />
      <TaskSplit queue={queue} wideFrom="lg" />
    </div>
  );
}
