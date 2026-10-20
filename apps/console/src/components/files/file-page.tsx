'use client';

import * as React from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { FileSearch, SearchX } from 'lucide-react';

import { ExtractDialog } from '@/components/files/extract-dialog';
import { FileDownloadButton } from '@/components/files/file-actions';
import { fileIcon } from '@/components/files/file-meta';
import { ReadAs } from '@/components/files/read-as';
import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { RouteTabs } from '@/components/shared/route-tabs';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useCan } from '@/hooks/me-queries';
import { useFileExtractions } from '@/hooks/extraction-queries';
import { useFile } from '@/hooks/file-queries';
import type { Extraction } from '@/lib/types/extractions';
import type { FileDetail } from '@/lib/types/files';

export interface FilePageContext {
  file: FileDetail;
  /** Newest first; empty until the file is read. */
  extractions: Extraction[];
  /** The newest finished read, the one the page shows. */
  latest: Extraction | null;
  openExtract: () => void;
  canExtract: boolean;
  /** Whether the person may correct a read's values (`documents.edit`). */
  canCorrect: boolean;
}

/**
 * A file's own page (Data Hub › Files › a file): its name and how it was read, Extract and Download, and a route per
 * tab. Each tab's page renders its body from the context this passes down.
 */
export function FilePage({ children }: { children: (ctx: FilePageContext) => React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const file = useFile(id);
  const extractions = useFileExtractions(id);
  // The read runs on documents-service and is recorded on the file: both cells, as the two services check them.
  const canRead = useCan('documents', 'run');
  const canRecord = useCan('files', 'create');
  const canExtract = canRead === true && canRecord === true;
  const canCorrect = useCan('documents', 'edit') === true;
  const [extracting, setExtracting] = React.useState(false);
  // The run the last Extract started rides in the address (?run=), so the tab it lands on links it and a reload keeps it.
  const params = useSearchParams();
  const lastRun = params.get('run');
  const waiting = params.get('waiting') === '1';

  if (file.isPending) return <RecordSkeleton />;
  if (file.isError)
    return (
      <PageLayout icon={FileSearch} title="File" backHref="/files">
        {(file.error as { status?: number }).status === 404 ? (
          <EmptyState icon={SearchX} title="File not found" description="It may have been deleted, or it belongs to another team." action={{ label: 'Back to files', href: '/files' }} />
        ) : (
          <QueryError what="this file" onRetry={() => file.refetch()} retrying={file.isFetching} error={file.error} />
        )}
      </PageLayout>
    );

  const f = file.data;
  const rows = extractions.data?.data ?? [];
  const latest = rows.find((r) => r.status === 'done' || r.status === 'unreadable') ?? null;
  const base = `/files/${encodeURIComponent(f.id)}`;
  const blocked = f.scan.status === 'clean' ? undefined : f.scan.status === 'pending' ? 'Still being scanned' : 'Not cleared by the scan';
  const fieldCount = latest?.schema?.length ?? 0;
  return (
    <PageLayout
      icon={fileIcon(f.name)}
      backHref="/files"
      title={f.name}
      badge={<ReadAs data={f.data} compact />}
      tabs={
        <RouteTabs
          tabs={[
            { href: base, label: 'Preview' },
            { href: `${base}/fields`, label: fieldCount ? `Fields · ${fieldCount}` : 'Fields' },
            { href: `${base}/versions`, label: `Versions · ${f.versions.length}` },
            { href: `${base}/activity`, label: rows.length ? `Activity · ${rows.length}` : 'Activity' },
          ]}
        />
      }
      actions={
        <>
          {canExtract && (
            <Button onClick={() => setExtracting(true)} disabled={!!blocked} title={blocked} data-testid="file-extract">
              <FileSearch className="size-4" /> Extract
            </Button>
          )}
          <FileDownloadButton fileId={f.id} name={f.name} blocked={blocked} />
        </>
      }
    >
      {lastRun && (
        <Alert className="mb-4" data-testid="file-last-run">
          <AlertDescription className="block">
            Read by{' '}
            <Link href={`/workflows/runs/${encodeURIComponent(lastRun)}`} className="font-medium underline underline-offset-2" data-testid="file-last-run-link">
              run {lastRun}
            </Link>
            {waiting ? ', waiting for a person to check fields in Human Tasks.' : '.'}
          </AlertDescription>
        </Alert>
      )}
      {children({ file: f, extractions: rows, latest, openExtract: () => setExtracting(true), canExtract, canCorrect })}
      <ExtractDialog open={extracting} onOpenChange={setExtracting} fileId={f.id} fileName={f.name} onDone={(run) => router.push(`${base}/fields?${new URLSearchParams({ run: run.runId, ...(run.status === 'waiting' ? { waiting: '1' } : {}) })}`)} />
    </PageLayout>
  );
}
