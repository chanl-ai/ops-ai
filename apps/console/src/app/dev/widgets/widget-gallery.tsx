'use client';

import * as React from 'react';

import { LayoutWidget } from '@/components/chat/widget-layout';
import { WidgetView } from '@/components/chat/widget-view';
import { JsonBlock } from '@/components/shared/json-block';
import { Section } from '@/components/shared/surface';
import type { LayoutPart, WidgetPart } from '@/lib/types/widgets';

/** Each part through WidgetView, then each layout (c-082) through LayoutWidget; approve, reject, submit and button
 * replies are recorded below instead of reaching a service. */
export function WidgetGallery({ parts, layouts = [] }: { parts: WidgetPart[]; layouts?: LayoutPart[] }) {
  const [log, setLog] = React.useState<unknown[]>([]);
  const record = (entry: unknown) => {
    setLog((l) => [...l, entry]);
    return Promise.resolve();
  };
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      {parts.map((p) => (
        <div key={p.id} className="flex flex-col gap-2" data-testid={`sample-${p.id}`}>
          <code className="font-mono text-xs text-muted-foreground">
            {p.id} · {p.shape}
            {p.hint?.prefer ? ` · prefers ${p.hint.prefer}` : ''}
          </code>
          <WidgetView
            part={p}
            actions={{
              onDecide: (holdId, approved, reason) => record({ widget: p.id, holdId, approved, ...(reason ? { reason } : {}) }),
              onSubmit: (values) => record({ widget: p.id, values }),
            }}
          />
        </div>
      ))}
      {layouts.map((p) => (
        <div key={p.id} className="flex flex-col gap-2" data-testid={`sample-${p.id}`}>
          <code className="font-mono text-xs text-muted-foreground">
            {p.id} · layout{p.template ? ` · ${p.template.id} v${p.template.version}` : ' · composed'}
          </code>
          <LayoutWidget part={p} onReply={(text) => void record({ widget: p.id, reply: text })} />
        </div>
      ))}
      <Section title="Actions" description="What each widget sent, in order.">
        <div data-testid="widget-log">
          <JsonBlock value={log} />
        </div>
      </Section>
    </div>
  );
}
