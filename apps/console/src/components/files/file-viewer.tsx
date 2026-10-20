'use client';

import { Loader2 } from 'lucide-react';

import { DocumentViewer, type ViewerBox } from '@/components/shared/document-viewer';
import { useFilePreviewUrl } from '@/hooks/extraction-queries';
import type { FileDetail } from '@/lib/types/files';

const viewable = (mime: string) => mime === 'application/pdf' || mime.startsWith('image/');

/**
 * The file's pages, drawn by the shared document viewer with each field's box over the text it was read from.
 */
export function FileViewer({ file, boxes, selected, onSelect }: { file: FileDetail; boxes?: ViewerBox[]; selected?: string | null; onSelect?: (key: string) => void }) {
  const clean = file.scan.status === 'clean';
  const preview = useFilePreviewUrl(file.id, clean && viewable(file.mime));
  const frame = 'h-[min(78vh,960px)] w-full rounded-lg border bg-muted/30';
  if (!clean) return <p className={`${frame} flex items-center justify-center p-6 text-sm text-muted-foreground`}>{file.scan.status === 'pending' ? 'Shown once the scan finishes.' : 'Not shown: the scan did not clear it.'}</p>;
  if (!viewable(file.mime)) return <p className="rounded-lg border p-6 text-sm text-muted-foreground">Preview shows PDFs and images. Download the file to open it.</p>;
  if (preview.error) return <p className={`${frame} flex items-center justify-center p-6 text-sm text-destructive`}>{preview.error}</p>;
  if (!preview.url)
    return (
      <div className={`${frame} flex items-center justify-center`} aria-busy="true">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </div>
    );
  return <DocumentViewer url={preview.url} mime={file.mime} boxes={boxes} selected={selected} onSelect={onSelect} className={frame} />;
}
