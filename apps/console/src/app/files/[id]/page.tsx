'use client';

import * as React from 'react';

import { FileFieldList } from '@/components/files/file-reads';
import { FilePage } from '@/components/files/file-page';
import { FileViewer } from '@/components/files/file-viewer';
import type { ViewerBox } from '@/components/shared/document-viewer';
import { SplitView } from '@/components/shared/setting/split-view';
import type { Extraction } from '@/lib/types/extractions';

/** Every box of the newest read's fields, a field to check marked, for the viewer. */
function boxesOf(read: Extraction | null): ViewerBox[] {
  const fields = read?.records?.[0]?.fields ?? read?.fields ?? {};
  return Object.entries(fields).flatMap(([key, f]) => (f.boxes ?? []).map((b) => ({ key, ...b, check: f.needsReview })));
}

/** A file's Preview tab: its pages with each field's box, and the newest read's fields beside them; each selects the other. */
export default function FilePreviewPage() {
  const [selected, setSelected] = React.useState<string | null>(null);
  return (
    <FilePage>
      {({ file, latest, openExtract, canExtract }) => (
        <SplitView
          id="file-preview"
          bare
          defaultLeft={60}
          leftMin="35"
          rightMin="30"
          left={<FileViewer file={file} boxes={boxesOf(latest)} selected={selected} onSelect={setSelected} />}
          right={<FileFieldList latest={latest} onExtract={openExtract} canExtract={canExtract} selected={selected} onSelect={setSelected} />}
        />
      )}
    </FilePage>
  );
}
