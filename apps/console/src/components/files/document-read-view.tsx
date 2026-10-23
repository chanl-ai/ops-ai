'use client';

import * as React from 'react';

import { FileViewer } from '@/components/files/file-viewer';
import { DocumentReadSection } from '@/components/reviews/document-read';
import { DocumentViewer, type ViewerBox } from '@/components/shared/document-viewer';
import { SplitView } from '@/components/shared/setting/split-view';
import { Skeleton } from '@/components/ui/skeleton';
import { useFile } from '@/hooks/file-queries';
import type { DocumentRead } from '@/lib/types/domain';

/** A file's bytes for the viewer when they are not a stored file: the design preview's sample. */
export type ReadDocument = { url: string; mime: string };

/** Every box of every record's fields, keyed `<record>:<field>`, a field to check marked. */
function boxesOf(read: DocumentRead): ViewerBox[] {
  return read.records.flatMap((r, i) =>
    Object.entries(r.fields).flatMap(([key, f]) => (f.boxes ?? []).map((b) => ({ key: `${i}:${key}`, ...b, check: f.needsReview && !f.corrected }))),
  );
}

function StoredFile({ fileId, boxes, selected, onSelect }: { fileId: string; boxes: ViewerBox[]; selected: string | null; onSelect: (key: string) => void }) {
  const file = useFile(fileId);
  if (file.isError) return <p className="rounded-lg border p-6 text-sm text-muted-foreground">The file could not be shown. Open it from Files.</p>;
  if (!file.data)
    return <Skeleton className="h-[min(70vh,820px)] w-full rounded-lg" data-testid="document-read-loading" />;
  return <FileViewer file={file.data} boxes={boxes} selected={selected} onSelect={onSelect} />;
}

/**
 * One document read shown beside its document: the pages with every field's place boxed (a field to check in the
 * warning colour) and, beside them, the records as the read check draws them, one tab per record with each field's
 * value, confidence and quote. Choosing a field's quote highlights where it was read. The one read view for a run's
 * read step, Human Tasks and the Files panel; it reads a `DocumentRead` and nothing else.
 */
export function DocumentReadView({ read, document }: { read: DocumentRead; document?: ReadDocument }) {
  const [selected, setSelected] = React.useState<string | null>(null);
  const boxes = boxesOf(read);
  return (
    <SplitView
      id="document-read"
      bare
      defaultLeft={50}
      leftMin="30"
      rightMin="35"
      left={
        document ? (
          <DocumentViewer url={document.url} mime={document.mime} boxes={boxes} selected={selected} onSelect={setSelected} className="h-[min(70vh,820px)] w-full rounded-lg border bg-muted/30" />
        ) : (
          <StoredFile fileId={read.fileId} boxes={boxes} selected={selected} onSelect={setSelected} />
        )
      }
      right={<DocumentReadSection read={read} open={false} edits={{}} onEdit={() => undefined} onOpenSource={(record, key) => setSelected(`${record}:${key}`)} />}
    />
  );
}

