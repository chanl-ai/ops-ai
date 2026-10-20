'use client';

import * as React from 'react';

import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { Cell, WidgetPart } from '@/lib/types/widgets';
import { toKind } from '@/lib/widgets/kinds';

import { pickRenderer, renderersFor } from './widget-registry';
import { KindView } from './widgets/kind-view';

/** What the thread lets a shaped widget do; both undefined when the conversation is read-only. */
export interface WidgetActions {
  /** Decides a decision widget's hold; the thread asks for a step-up first when the hold needs one. */
  onDecide?: (holdId: string, approved: boolean, reason?: string) => Promise<unknown>;
  onSubmit?: (values: Record<string, Cell>) => Promise<unknown>;
}

/**
 * One shaped tool result in a message: the registry picks how to draw it, the choice becomes a kind
 * (lib/widgets/kinds.ts), and the kind renderers draw it like any other widget. When the shape has more than one way
 * to draw it (chart or table), a switch between them; the choice lasts as long as the message is on screen.
 */
export function WidgetView({ part, actions = {} }: { part: WidgetPart; actions?: WidgetActions }) {
  const [chosen, setChosen] = React.useState<string>();
  const options = renderersFor(part);
  const resolved = pickRenderer(part, chosen);
  const node = toKind(resolved, part.hint ?? undefined);
  const holdId = part.shape === 'decision' ? part.data.holdId : undefined;
  return (
    <section className="flex flex-col gap-2" aria-label={part.hint?.title ?? resolved.label} data-testid="widget" data-shape={part.shape} data-renderer={resolved.id}>
      {(part.hint?.title || options.length > 1) && node.type !== 'entity' && node.type !== 'form' && node.type !== 'tracker' && (
        <header className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm font-medium">{part.hint?.title}</span>
          {options.length > 1 && (
            <ToggleGroup type="single" size="sm" value={resolved.id} onValueChange={(v) => v && setChosen(v)} aria-label="Show as">
              {options.map((o) => (
                <ToggleGroupItem key={o.id} value={o.id} className="px-2 text-xs">
                  {o.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        </header>
      )}
      <div className={node.type === 'table' || node.type === 'chart' ? 'overflow-hidden rounded-lg border bg-card' : undefined}>
        <KindView
          node={node}
          truncatedFrom={part.hint?.truncatedFrom}
          actions={{
            onSubmit: actions.onSubmit,
            onAnswer: holdId && actions.onDecide ? (yes) => actions.onDecide!(holdId, yes) : undefined,
          }}
        />
      </div>
    </section>
  );
}
