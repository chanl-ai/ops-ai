'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import { BadgeCheck, ChevronLeft, ChevronRight, Folder, Sparkles, Type } from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { SplitView } from '@/components/shared/setting/split-view';
import { FileDownloadButton } from '@/components/files/file-actions';
import { FileViewer } from '@/components/files/file-viewer';
import { READ_BY } from '@/components/knowledge/document-sheet';
import { blockById, DocumentText, textBoxes } from '@/components/knowledge/document-text';
import { FreshnessBadge, MimeIcon } from '@/components/knowledge/knowledge-meta';
import { useFile } from '@/hooks/file-queries';
import { useItem, useItemText, useVerifyItem } from '@/hooks/knowledge-queries';
import { useCan } from '@/hooks/me-queries';
import { mimeLabel, plural, shortDate } from '@/lib/format';
import type { ItemText, ItemTextBlock } from '@/lib/types/knowledge';

/** The original's pages one at a time, with the text's highlights on the page shown. */
function Original({ fileId, text, page, onPage, selected, onSelect }: { fileId: string; text: ItemText | undefined; page: number; onPage: (n: number) => void; selected: string | null; onSelect: (key: string) => void }) {
  const file = useFile(fileId);
  const pages = text?.paged ? text.pages.length : 0;
  if (file.isError) return <p className="rounded-lg border p-6 text-sm text-muted-foreground">The original could not be shown. Download it to open it.</p>;
  if (!file.data) return <Skeleton className="h-[min(78vh,960px)] w-full rounded-lg" data-testid="document-original-loading" />;
  return (
    <div className="flex flex-col gap-2">
      {pages > 1 && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-muted-foreground tabular-nums" data-testid="document-page-label">
            Page {page} of {pages}
          </span>
          <div className="flex gap-1">
            <Button size="icon" variant="outline" aria-label="Previous page" data-testid="document-page-previous" disabled={page <= 1} onClick={() => onPage(page - 1)}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button size="icon" variant="outline" aria-label="Next page" data-testid="document-page-next" disabled={page >= pages} onClick={() => onPage(page + 1)}>
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
      <FileViewer file={file.data} boxes={text ? textBoxes(text) : []} selected={selected} onSelect={onSelect} page={pages > 1 ? page : undefined} />
    </div>
  );
}

/**
 * One knowledge document: the original on the left, what was read from it on the right, section by section.
 * Choosing a paragraph turns to its page and highlights its lines; choosing a highlight selects its paragraph.
 * `?page=` opens at a cited page.
 */
export default function KnowledgeDocumentPage() {
  const { itemId } = useParams<{ itemId: string }>();
  const asked = Number(useSearchParams().get('page')) || 1;
  const item = useItem(itemId);
  const text = useItemText(itemId);
  const verify = useVerifyItem();
  const canVerify = useCan('knowledge', 'edit') === true;
  const [page, setPage] = React.useState(asked);
  const [selected, setSelected] = React.useState<string | null>(null);
  React.useEffect(() => {
    setPage(asked);
  }, [asked, itemId]);

  if (item.isPending) return <PageLayout title="Document" backHref="/data/knowledge"><PageSkeleton tableRows={6} showToolbar={false} /></PageLayout>;
  if (item.isError)
    return (
      <PageLayout title="Document" backHref="/data/knowledge">
        <QueryError what="this document" onRetry={() => item.refetch()} retrying={item.isFetching} error={item.error} back={{ label: 'Back to knowledge bases', href: '/data/knowledge' }} />
      </PageLayout>
    );

  const it = item.data;
  const t = text.data;
  const readBy = [...new Set((t?.pages ?? []).map((p) => p.readBy).filter((r) => r !== 'none'))];
  const choose = (b: ItemTextBlock) => {
    setSelected(b.id);
    if (b.page) setPage(b.page);
  };
  const fromBox = (key: string) => {
    if (t && blockById(t, key)) setSelected(key);
  };
  const facts = [mimeLabel(it.mimeType), it.pageCount ? plural(it.pageCount, 'page') : null, it.version ? `version ${it.version}` : null, it.modifiedAt ? `changed ${shortDate(it.modifiedAt)}` : null].filter(Boolean).join(' · ');

  return (
    <PageLayout
      icon={<MimeIcon mime={it.mimeType} />}
      title={it.title}
      recordName={it.title}
      backHref="/data/knowledge"
      description={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>{facts}</span>
          <FreshnessBadge reviewBy={it.reviewBy} freshness={it.freshness} />
          <Link href={`/data/sources/${it.sourceId}`} className="inline-flex items-center gap-1 rounded-md hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
            <Folder className="size-3.5" /> {it.sourceName}
          </Link>
          {readBy.length > 0 && (
            <span className="flex items-center gap-1" data-testid="document-read-by">
              Read by
              {readBy.map((r) => (
                <Badge key={r} variant="outline" className={r === 'model' ? 'gap-1 border-success/40 font-normal text-success-text' : 'gap-1 font-normal'}>
                  {r === 'model' ? <Sparkles className="size-3" /> : <Type className="size-3" />} {r === 'model' ? 'A model' : READ_BY[r] ?? r}
                </Badge>
              ))}
            </span>
          )}
        </span>
      }
      actions={
        <div className="flex gap-2">
          {it.fileId && <FileDownloadButton fileId={it.fileId} name={it.path.split('/').pop() ?? it.title} label="Download original" />}
          {canVerify && (
            <Button
              variant="outline"
              disabled={verify.isPending}
              data-testid="document-verify"
              onClick={() =>
                verify.mutate({ id: it.id, verified: !it.verified }, { onSuccess: () => toast.success(it.verified ? 'Verification removed' : 'Marked verified'), onError: (e) => toast.error('Couldn’t update verification', { description: e.message }) })
              }
            >
              <BadgeCheck className="size-4" /> {it.verified ? 'Remove verification' : 'Verify'}
            </Button>
          )}
        </div>
      }
    >
      <SplitView
        id="knowledge-document"
        bare
        defaultLeft={45}
        leftMin="30"
        rightMin="35"
        left={it.fileId ? <Original fileId={it.fileId} text={t} page={page} onPage={setPage} selected={selected} onSelect={fromBox} /> : <p className="rounded-lg border p-6 text-sm text-muted-foreground">This document has no original file; its text is on the right.</p>}
        right={
          text.isError ? (
            <QueryError what="the text read from this document" onRetry={() => text.refetch()} retrying={text.isFetching} error={text.error} />
          ) : !t ? (
            <div className="flex flex-col gap-3" data-testid="document-text-loading">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </div>
          ) : (
            <DocumentText text={t} selected={selected} onSelect={choose} />
          )
        }
      />
    </PageLayout>
  );
}
