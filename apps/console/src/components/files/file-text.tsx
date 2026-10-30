'use client';

import * as React from 'react';
import { Copy } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { plural } from '@/lib/format';
import type { DocumentLayout } from '@/lib/types/extractions';

/** Under this a word is marked: the same factor the scorer applies to a value read from OCR'd words. */
const LOW = 0.7;

type Block = DocumentLayout['blocks'][number];
/** A piece of a block's text, with the confidence it was read at when that is under the floor. */
type Part = { text: string; conf?: number };

/**
 * Each page's blocks in reading order, split into words and the space between them. A word is marked when the page
 * has a word with the same text read under the floor, matched in reading order, so each low word marks one word.
 */
function pagesOf(layout: DocumentLayout) {
  const numbers = layout.pages.length ? layout.pages.map((p) => p.number).sort((a, b) => a - b) : [...new Set(layout.blocks.map((b) => b.page))].sort((a, b) => a - b);
  return numbers.map((n) => {
    const blocks = layout.blocks.filter((b) => b.page === n).sort((a, b) => a.order - b.order);
    const low = new Map<string, number[]>();
    for (const w of layout.words) if (w.page === n && w.conf < LOW) low.set(w.text, [...(low.get(w.text) ?? []), w.conf]);
    const parts = blocks.map((b) => b.text.split(/(\s+)/).map((text): Part => ({ text, conf: text.trim() ? low.get(text)?.shift() : undefined })));
    return { number: n, blocks: blocks.map((b, i) => ({ block: b, parts: parts[i] })), text: blocks.map((b) => b.text).join('\n') };
  });
}

/** Two decimals, rounded down, so a word under the floor never reads as at it. */
const shown = (conf: number) => (Math.floor(conf * 100) / 100).toFixed(2);

/** A block's text with each word read under the floor marked with its confidence. */
function BlockText({ block, parts }: { block: Block; parts: Part[] }) {
  const heading = block.kind === 'title' || block.kind === 'heading';
  return (
    <p className={heading ? 'font-medium' : block.kind === 'table' ? 'whitespace-pre-wrap' : undefined}>
      {parts.map((part, i) =>
        part.conf === undefined ? (
          <React.Fragment key={i}>{part.text}</React.Fragment>
        ) : (
          <mark key={i} data-confidence={shown(part.conf)} title={`Read with ${Math.round(part.conf * 100)}% confidence`} className="rounded-sm bg-warning/25 px-0.5 text-foreground">
            {part.text}
          </mark>
        ),
      )}
    </p>
  );
}

const copy = async (text: string, what: string) => {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`Copied ${what}`);
  } catch {
    toast.error('Couldn’t copy', { description: 'The browser did not allow it. Select the text and copy it instead.' });
  }
};

/**
 * A file's full text, every page in order in its own block ("Page N of M"), each word read with low confidence marked
 * with its confidence. Copy page and Copy all copy the text as read; Go to page scrolls to a page.
 */
export function FileTextPages({ layout }: { layout: DocumentLayout }) {
  const pages = React.useMemo(() => pagesOf(layout), [layout]);
  const lowCount = layout.words.filter((w) => w.conf < LOW).length;
  const total = pages.length;
  const refs = React.useRef(new Map<number, HTMLElement>());
  if (total === 0) return <p className="rounded-lg border p-6 text-sm text-muted-foreground">No text was found in this file.</p>;
  return (
    <div className="flex min-w-0 flex-col gap-3" data-testid="file-text">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {plural(total, 'page')}
          {lowCount ? ` · ${plural(lowCount, 'word')} read with low confidence marked` : ''}
        </p>
        <div className="flex items-center gap-2">
          {total > 1 && (
            <Select onValueChange={(v) => refs.current.get(Number(v))?.scrollIntoView({ block: 'start', behavior: 'smooth' })}>
              <SelectTrigger size="sm" className="w-36" aria-label="Go to page" data-testid="file-text-goto">
                <SelectValue placeholder="Go to page" />
              </SelectTrigger>
              <SelectContent>
                {pages.map((p) => (
                  <SelectItem key={p.number} value={String(p.number)}>
                    Page {p.number}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Button variant="outline" size="sm" onClick={() => void copy(pages.map((p) => p.text).join('\n\n'), 'all pages')} data-testid="file-text-copy-all">
            <Copy className="size-4" /> Copy all
          </Button>
        </div>
      </div>
      {pages.map((p) => (
          <section
            key={p.number}
            ref={(el) => void (el ? refs.current.set(p.number, el) : refs.current.delete(p.number))}
            className="min-w-0 scroll-mt-4 rounded-lg border"
            data-testid="file-text-page"
            data-page={p.number}
          >
            <header className="flex items-center justify-between gap-2 border-b px-4 py-2">
              <h2 className="text-sm font-medium">
                Page {p.number} of {total}
              </h2>
              <Button variant="ghost" size="sm" onClick={() => void copy(p.text, `page ${p.number}`)} disabled={!p.text} data-testid="file-text-copy-page">
                <Copy className="size-4" /> Copy page
              </Button>
            </header>
            <div className="flex min-w-0 flex-col gap-2 px-4 py-3 text-sm break-words">
              {p.blocks.length ? p.blocks.map(({ block, parts }) => <BlockText key={block.id} block={block} parts={parts} />) : <p className="text-muted-foreground">This page has no text. It may be blank, or a photo with no words.</p>}
            </div>
          </section>
      ))}
    </div>
  );
}

/** The Text tab while the layout is read: the shape of a page block. */
export function FileTextSkeleton() {
  return (
    <div className="flex flex-col gap-3" data-testid="file-text-loading">
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-64 w-full rounded-lg" />
    </div>
  );
}
