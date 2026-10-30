'use client';

import { notFound } from 'next/navigation';

import { FilePage } from '@/components/files/file-page';
import { FileTextPages, FileTextSkeleton } from '@/components/files/file-text';
import { QueryError } from '@/components/shared/query-states';
import { useFileLayout } from '@/hooks/extraction-queries';
import { documentReads } from '@/lib/api';

/** A file's Text tab: every page's text in reading order, words read with low confidence marked. No model call. */
export default function FileTextPage() {
  if (!documentReads) notFound();
  return <FilePage>{({ file }) => <FileTextTab fileId={file.id} />}</FilePage>;
}

function FileTextTab({ fileId }: { fileId: string }) {
  const layout = useFileLayout(fileId);
  if (layout.isPending) return <FileTextSkeleton />;
  if (layout.isError) return <QueryError what="this file's text" onRetry={() => layout.refetch()} retrying={layout.isFetching} error={layout.error} />;
  return <FileTextPages layout={layout.data} />;
}
