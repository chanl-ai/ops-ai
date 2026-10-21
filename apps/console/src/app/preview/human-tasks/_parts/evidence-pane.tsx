'use client';

import * as React from 'react';
import { FileText } from 'lucide-react';

import { DocumentViewer } from '@/components/shared/document-viewer';
import { cn } from '@/lib/utils';

import type { QueueItem, Task } from '../_sample/data';

/**
 * The document the task is about, with the fields read from it boxed: the open task's fields only, so on a notice
 * naming three people the boxes move to the person being decided. The pane scrolls on its own; the decision beside it
 * does not move.
 */
export function EvidencePane({ item, task, className }: { item: QueueItem; task: Task; className?: string }) {
  const [selected, setSelected] = React.useState<string | null>(null);
  React.useEffect(() => {
    setSelected(null);
  }, [task.id]);
  // The amount the task turns on is drawn in the warning colour; the other fields it read are boxed plainly.
  const boxes = item.document.boxes.filter((b) => task.fields.includes(b.key) || b.key === 'file').map((b) => ({ ...b, check: b.key === task.fields[0] }));
  return (
    <section className={cn('flex min-h-0 min-w-0 flex-col gap-2', className)} aria-label="Evidence" data-testid="evidence-pane">
      <header className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 px-1">
        <span className="flex min-w-0 items-center gap-1.5 text-sm font-medium">
          <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate">{item.document.name}</span>
        </span>
        <span className="text-xs text-muted-foreground">
          {item.source}, {item.received}
        </span>
      </header>
      {/* The pane scrolls, not the viewer: a viewer held to the pane's height lays its pages out in a flex column that
          shrinks them to fit, so a two-page notice would draw squashed. */}
      <div className="min-h-0 flex-1 overflow-y-auto" data-testid="evidence-scroll">
        <DocumentViewer url={item.document.url} mime="application/pdf" boxes={boxes} selected={selected} onSelect={setSelected} className="min-h-96" />
      </div>
    </section>
  );
}
