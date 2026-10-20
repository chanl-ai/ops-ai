'use client';

import { FileFields } from '@/components/files/file-reads';
import { FilePage } from '@/components/files/file-page';
import { useDocumentType } from '@/hooks/document-type-queries';

/** A file's Fields tab: the newest read, one row per field with its value, confidence and quote. */
export default function FileFieldsPage() {
  return (
    <FilePage>
      {({ file, latest, openExtract, canExtract, canCorrect }) => (
        <div className="flex flex-col gap-3" data-testid="file-fields">
          {latest?.documentType && (
            <p className="text-xs text-muted-foreground" data-testid="file-read-line">
              Read as <TypeName id={latest.documentType.id} fallback={file.data?.typeName} /> v{latest.documentType.version}
              {latest.pages ? ` · ${latest.pages === 1 ? '1 page' : `${latest.pages} pages`}` : ''}
            </p>
          )}
          <FileFields latest={latest} fileName={file.name} onExtract={openExtract} canExtract={canExtract} canEdit={canCorrect} />
        </div>
      )}
    </FilePage>
  );
}

/** The document type's name, read once by its id; the id until it arrives. */
function TypeName({ id, fallback }: { id: string; fallback?: string | null }) {
  const t = useDocumentType(id);
  return <>{t.data?.name ?? fallback ?? id}</>;
}
