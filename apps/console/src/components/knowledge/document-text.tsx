'use client';

import * as React from 'react';
import { Info, Sparkles } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { ViewerBox } from '@/components/shared/document-viewer';
import type { ItemText, ItemTextBlock } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

/** Every block's places on its page, keyed by the block's id, so selecting a paragraph lights all its lines. */
export function textBoxes(text: ItemText): ViewerBox[] {
  return text.sections.flatMap((s) => s.blocks.flatMap((b) => b.boxes.map((x) => ({ key: b.id, ...x }))));
}

/** The block with this id and the page it sits on, for selecting from a box on the page. */
export function blockById(text: ItemText, id: string): ItemTextBlock | undefined {
  for (const s of text.sections) for (const b of s.blocks) if (b.id === id) return b;
  return undefined;
}

/**
 * What was read from a document, section by section, beside the original. Each paragraph is a button: choosing it
 * selects it and the viewer highlights where it sits. A model's description of a picture is marked so it is not taken
 * for the author's words, and pages left unread say why at the end.
 */
export function DocumentText({ text, selected, onSelect }: { text: ItemText; selected: string | null; onSelect: (block: ItemTextBlock) => void }) {
  const holder = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!selected) return;
    holder.current?.querySelector(`[data-block="${CSS.escape(selected)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selected]);
  const byModel = text.pages.filter((p) => p.readBy === 'model').map((p) => p.number);
  const lines = text.sections.some((s) => s.blocks.some((b) => b.boxes.length > 1));

  return (
    <div ref={holder} className="flex flex-col gap-4" data-testid="document-text">
      {byModel.length > 0 && (
        <Alert>
          <Sparkles className="size-4" />
          <AlertTitle>{byModel.length === 1 ? `Page ${byModel[0]} has no text. A model read the picture.` : `${byModel.length} pages have no text. A model read their pictures.`}</AlertTitle>
          <AlertDescription>The words marked Read by a model were written by a model looking at the page. Check them against the page before you rely on them.</AlertDescription>
        </Alert>
      )}
      {text.sections.length === 0 && text.status === 'done' && <p className="text-sm text-muted-foreground">No text was read from this document.</p>}
      {text.sections.map((s) => (
        <section key={s.id} className="flex flex-col gap-2" aria-label={s.headingPath.join(' > ') || 'Opening'}>
          <div className="flex items-start justify-between gap-3">
            <h3 className="text-sm font-semibold">{s.headingPath.at(-1) ?? 'Opening'}</h3>
            {s.page != null && (
              <Badge variant="outline" className="shrink-0 font-normal tabular-nums">
                p. {s.page}
              </Badge>
            )}
          </div>
          {s.blocks.map((b) => (
            <button
              key={b.id}
              type="button"
              data-block={b.id}
              aria-pressed={selected === b.id}
              onClick={() => onSelect(b)}
              className={cn(
                'rounded-md px-2 py-1 text-left text-sm whitespace-pre-line transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                b.kind === 'table' && 'font-mono text-xs',
                selected === b.id && 'bg-primary/10 ring-1 ring-primary/40 hover:bg-primary/10',
              )}
            >
              {b.readBy === 'model' && (
                <Badge variant="outline" className="mb-1 gap-1 border-success/40 font-normal text-success-text">
                  <Sparkles className="size-3" /> Read by a model{b.page != null ? ` · page ${b.page}` : ''}
                </Badge>
              )}
              <span className="block">{b.text}</span>
            </button>
          ))}
        </section>
      ))}
      {text.notes.map((n) => (
        <p key={n} className="flex items-start gap-2 text-xs text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" /> {n}
        </p>
      ))}
      {text.paged && text.sections.length > 0 && (
        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" />
          {lines ? 'Choose a paragraph to highlight its lines on the page, or a highlight to find its paragraph.' : 'Choose a paragraph to highlight where it sits on the page.'}
        </p>
      )}
    </div>
  );
}
