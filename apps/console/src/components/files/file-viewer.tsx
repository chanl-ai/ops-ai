'use client';

import { Loader2 } from 'lucide-react';

import { DocumentViewer, type ViewerBox } from '@/components/shared/document-viewer';
import { useFilePreviewUrl } from '@/hooks/extraction-queries';
import type { FileDetail } from '@/lib/types/files';

const viewable = (mime: string) => mime === 'application/pdf' || mime.startsWith('image/');

/**
 * The file's pages, drawn by the shared document viewer with each field's box over the text it was read from.
 */
export function FileViewer({ file, boxes, selected, onSelect, page }: { file: FileDetail; boxes?: ViewerBox[]; selected?: string | null; onSelect?: (key: string) => void; page?: number }) {
  const clean = file.scan.status === 'clean';
  const preview = useFilePreviewUrl(file.id, clean && viewable(file.mime));
  const frame = 'h-[min(78vh,960px)] w-full rounded-lg border bg-muted/30';
  if (!clean) return <p className={`${frame} flex items-center justify-center p-6 text-sm text-muted-foreground`}>{file.scan.status === 'pending' ? 'Shown once the scan finishes.' : 'Not shown: the scan did not clear it.'}</p>;
  if (!viewable(file.mime)) return <p className="rounded-lg border p-6 text-sm text-muted-foreground">Preview shows PDFs and images. Download the file to open it.</p>;
  if (preview.error) return <p className={`${frame} flex items-center justify-center p-6 text-sm text-destructive-text`}>{preview.error}</p>;
  if (!preview.url)
    return (
      <div className={`${frame} flex items-center justify-center`} aria-busy="true">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  // One page at a time sizes to that page, so a wide slide leaves no empty frame below it (and on a phone, the text
  // beside it stays in reach); every page at once scrolls inside the fixed frame.
  const shown = page ? 'max-h-[min(78vh,960px)] w-full rounded-lg border bg-muted/30' : frame;
  return <DocumentViewer url={preview.url} mime={file.mime} boxes={boxes} selected={selected} onSelect={onSelect} page={page} className={shown} />;
}
