'use client';

import * as React from 'react';
import { Sparkles } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import type { Cell, LayoutNode, LayoutPart, Tone } from '@/lib/types/widgets';

import { KindView } from './widgets/kind-view';

// A checked layout (c-082): the kernel rebuilt it from catalogue primitives, so every node type here is one this file
// draws. Metrics, tables, charts and the c-176 kinds draw through the kind renderers, so a template, a composed layout
// and a shaped result look the same.

const TONE: Record<Tone, string> = {
  neutral: '',
  info: 'border-primary/30 bg-primary/10 text-primary',
  success: 'border-success/30 bg-success/10 text-success-text',
  warning: 'border-warning/30 bg-warning/10 text-warning-text',
  danger: 'border-destructive/30 bg-destructive/10 text-destructive',
};
const GAP = { sm: 'gap-2', md: 'gap-3', lg: 'gap-4' } as const;
const ALIGN = { start: 'items-start', center: 'items-center', end: 'items-end', between: 'items-center justify-between' } as const;

const text = (v: Cell | undefined) => (v === null || v === undefined ? '—' : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : typeof v === 'number' ? v.toLocaleString() : v);

/**
 * What a button does: send its reply as the person's next message, the only thing a widget can do (owner Q3). A
 * button that `requires` a tool names it as the action, so the agent's turn knows which of its tools was asked for.
 */
export function replyText(reply: { text: string; values?: Record<string, Cell> }, requires?: string): string {
  const parts = [...(requires ? [`action: ${requires}`] : []), ...Object.entries(reply.values ?? {}).map(([k, v]) => `${k}: ${text(v)}`)];
  return parts.length ? `${reply.text} (${parts.join(', ')})` : reply.text;
}

function Node({ node, onReply }: { node: LayoutNode; onReply?: (text: string) => void }): React.ReactNode {
  switch (node.type) {
    case 'card':
      return (
        <div className="flex flex-col gap-3">
          {node.title && <h3 className="text-sm font-semibold">{node.title}</h3>}
          {node.children.map((c, i) => <Node key={i} node={c} onReply={onReply} />)}
        </div>
      );
    case 'row':
      return <div className={cn('flex flex-wrap', GAP[node.gap ?? 'md'], ALIGN[node.align ?? 'center'])}>{node.children.map((c, i) => <Node key={i} node={c} onReply={onReply} />)}</div>;
    case 'column':
      return <div className={cn('flex flex-col', GAP[node.gap ?? 'md'])}>{node.children.map((c, i) => <Node key={i} node={c} onReply={onReply} />)}</div>;
    case 'title':
      return <p className="text-sm font-semibold">{node.text}</p>;
    case 'text':
      return <p className="text-sm">{node.text}</p>;
    case 'caption':
      return <p className="text-xs text-muted-foreground">{node.text}</p>;
    case 'badge':
      return (
        <Badge variant="outline" className={TONE[node.tone ?? 'neutral']}>
          {node.text}
        </Badge>
      );
    case 'keyValue':
      return (
        <dl className="grid grid-cols-[minmax(6rem,auto)_1fr] gap-x-4 gap-y-1 text-sm">
          {node.items.map((it, i) => (
            <React.Fragment key={i}>
              <dt className="text-muted-foreground">{it.label}</dt>
              <dd className="min-w-0 break-words">{text(it.value)}</dd>
            </React.Fragment>
          ))}
        </dl>
      );
    case 'list':
      return (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {node.items.map((it, i) => (
            <li key={i}>{text(it)}</li>
          ))}
        </ul>
      );
    case 'button':
      return (
        <Button size="sm" variant="outline" className="self-start" disabled={!onReply} onClick={() => onReply?.(replyText(node.reply, node.requires))} title={onReply ? `Sends: ${replyText(node.reply, node.requires)}` : undefined}>
          {node.label}
        </Button>
      );
    case 'divider':
      return <Separator />;
    case 'image':
      // Images are never fetched in chat (docs/console/chat.md); the kernel drops the source.
      return <p className="text-xs text-muted-foreground">[Image blocked: {node.alt}]</p>;
    default:
      return <KindView node={node} actions={{ onReply }} />;
  }
}

/** A widget layout in a message, with a line saying which widget it is or that the agent composed it (CW12). */
export function LayoutWidget({ part, onReply }: { part: LayoutPart; onReply?: (text: string) => void }) {
  if (part.kind)
    // One generic kind (c-176) is its own card: no frame, and no "composed" line, since the agent filled a fixed kind.
    return (
      <section aria-label={part.kind} data-testid="widget" data-shape="kind" data-kind={part.kind}>
        <KindView node={part.layout as Parameters<typeof KindView>[0]['node']} actions={{ onReply }} />
      </section>
    );
  return (
    <section className="overflow-hidden rounded-lg border bg-card" aria-label={part.template?.name ?? 'Composed by the agent'} data-testid="widget" data-shape="layout" data-template={part.template?.id ?? ''}>
      <div className="p-3">
        <Node node={part.layout} onReply={onReply} />
      </div>
      <footer className="flex items-center gap-1.5 border-t px-3 py-1 text-[11px] text-muted-foreground">
        {part.template ? (
          <span>
            {part.template.name} · v{part.template.version}
          </span>
        ) : (
          <>
            <Sparkles className="size-3" aria-hidden /> Composed by the agent
          </>
        )}
      </footer>
    </section>
  );
}
