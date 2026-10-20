'use client';

import * as React from 'react';
import { Loader2 } from 'lucide-react';

import { cn } from '@/lib/utils';

/** Where a field's value sits on a page, as fractions of the page from its top left (documents-service, c-252). */
export interface ViewerBox {
  key: string;
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
  /** A field to check draws in the warning colour. */
  check?: boolean;
}

type PdfPage = { getViewport(o: { scale: number }): { width: number; height: number }; render(o: { canvasContext: CanvasRenderingContext2D; viewport: unknown }): { promise: Promise<void> } };
type PdfDoc = { numPages: number; getPage(n: number): Promise<PdfPage> };

/**
 * A document's pages drawn with pdf.js, so each field's box can sit over the text it was read from. Selecting a field
 * highlights its boxes and scrolls them into view; clicking a box selects its field. An image is one page. Shared by
 * the file page and the read check.
 */
export function DocumentViewer({
  url,
  mime,
  boxes = [],
  selected,
  onSelect,
  className,
}: {
  url: string;
  mime: string;
  boxes?: ViewerBox[];
  selected?: string | null;
  onSelect?: (key: string) => void;
  className?: string;
}) {
  const [pages, setPages] = React.useState<{ src: string; width: number; height: number }[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const holder = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    let live = true;
    setPages(null);
    setError(null);
    if (mime.startsWith('image/')) {
      const img = new Image();
      img.onload = () => live && setPages([{ src: url, width: img.naturalWidth, height: img.naturalHeight }]);
      img.onerror = () => live && setError('The image could not be shown.');
      img.src = url;
      return () => {
        live = false;
      };
    }
    // pdf.js 6 frees a document through the task that loaded it; the document itself has no destroy.
    let task: { promise: Promise<unknown>; destroy(): Promise<void> } | null = null;
    (async () => {
      const pdfjs = await import('pdfjs-dist');
      pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString();
      // Uploaded documents are untrusted. Pages are drawn to a canvas with no annotation layer, which is where PDF.js
      // binds a document's scripts, and XFA forms (which render as HTML) stay off whatever the library's default.
      task = pdfjs.getDocument({ url, enableXfa: false });
      const doc = (await task.promise) as unknown as PdfDoc;
      // Each page is drawn once at twice its natural size and shown as an image, so it stays sharp when the frame resizes.
      const drawn: { src: string; width: number; height: number }[] = [];
      for (let n = 1; n <= doc.numPages; n++) {
        const page = await doc.getPage(n);
        const viewport = page.getViewport({ scale: 2 });
        const canvas = document.createElement('canvas');
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
        drawn.push({ src: canvas.toDataURL('image/png'), width: viewport.width, height: viewport.height });
      }
      if (live) setPages(drawn);
    })().catch((e: Error) => live && setError(`The document could not be shown: ${e.message}`));
    return () => {
      live = false;
      void task?.destroy();
    };
  }, [url, mime]);

  React.useEffect(() => {
    if (!selected || !holder.current) return;
    holder.current.querySelector(`[data-box-key="${CSS.escape(selected)}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [selected, pages]);

  if (error) return <p className={cn('flex items-center justify-center rounded-lg border p-6 text-sm text-destructive', className)}>{error}</p>;
  if (!pages)
    return (
      <div className={cn('flex items-center justify-center rounded-lg border bg-muted/30', className)} aria-busy="true">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  return (
    <div ref={holder} className={cn('flex flex-col gap-3 overflow-auto rounded-lg border bg-muted/30 p-3', className)} data-testid="document-viewer">
      {pages.map((p, i) => (
        <div key={i} className="relative w-full overflow-hidden rounded-sm bg-white shadow-xs" style={{ aspectRatio: `${p.width} / ${p.height}` }} data-testid={`viewer-page-${i + 1}`}>
          {/* eslint-disable-next-line @next/next/no-img-element -- a rendered page held in memory */}
          <img src={p.src} alt={`Page ${i + 1}`} className="absolute inset-0 size-full" />
          {boxes
            .filter((b) => b.page === i + 1)
            .map((b, j) => (
              <button
                key={`${b.key}-${j}`}
                type="button"
                aria-label={`Select ${b.key}`}
                data-box-key={b.key}
                data-selected={selected === b.key ? 'true' : 'false'}
                onClick={() => onSelect?.(b.key)}
                className={cn(
                  'absolute rounded-[2px] border-2 transition-colors',
                  b.check ? 'border-warning/80 bg-warning/15' : 'border-primary/60 bg-primary/10',
                  selected === b.key && 'border-primary bg-primary/25 ring-2 ring-primary/40',
                )}
                style={{ left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%` }}
              />
            ))}
        </div>
      ))}
    </div>
  );
}
