'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Layers } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { BatchCheck, type CheckedFile } from '@/components/workflows/start-from-file';
import { useStartBatch } from '@/hooks/batch-queries';
import { useDefinition } from '@/hooks/engine-queries';
import { plural } from '@/lib/format';
import type { BatchMode } from '@/lib/types/batches';

/**
 * Start from a file, after the Start run dialog picked the file: the dry run, the columns each input takes and
 * the first rows, then Start runs. Its own page because a dialog stays small; the dialog only picks.
 */
export default function CheckBatchPage() {
  const params = useSearchParams();
  const workflowId = params.get('workflow') ?? '';
  const fileId = params.get('file') ?? '';
  if (!workflowId || !fileId)
    return (
      <PageLayout icon={Layers} title="Start from a file" backHref="/build/workflows">
        <EmptyState
          icon={Layers}
          title="No file to start from"
          description="Open a workflow, choose Start run, then Start from a file."
        />
      </PageLayout>
    );
  const mode: BatchMode = params.get('mode') === 'test' ? 'test' : 'live';
  return <NewBatch workflowId={workflowId} file={{ fileId, name: params.get('name') ?? fileId }} mode={mode} />;
}

function NewBatch({ workflowId, file, mode }: { workflowId: string; file: { fileId: string; name: string }; mode: BatchMode }) {
  const router = useRouter();
  const definition = useDefinition(workflowId);
  const { mutateAsync: startBatch, isPending } = useStartBatch(workflowId);
  const [checked, setChecked] = React.useState<CheckedFile | null>(null);
  const [startError, setStartError] = React.useState<string>();
  const back = `/build/workflows/definitions/${encodeURIComponent(workflowId)}`;

  if (definition.isPending) return <PageSkeleton />;
  if (definition.isError)
    return (
      <PageLayout icon={Layers} title="Start from a file" backHref="/build/workflows">
        <QueryError what="this workflow" onRetry={() => definition.refetch()} retrying={definition.isFetching} error={definition.error} />
      </PageLayout>
    );
  const view = definition.data;
  const name = view.name || view.definition.name || workflowId;
  const inputs = (view.startForm?.schema?.properties ?? {}) as Record<string, { title?: string }>;

  const start = async () => {
    if (!checked) return;
    setStartError(undefined);
    try {
      const batch = await startBatch({ fileId: checked.fileId, mode });
      router.push(`/build/runs/batches/${encodeURIComponent(batch.id)}`);
    } catch (e) {
      setStartError(e instanceof Error ? e.message : 'The runs did not start');
    }
  };

  return (
    <PageLayout
      icon={Layers}
      title={`Start from a file: ${name}`}
      description={`${mode === 'test' ? 'Test runs on the latest saved version' : 'Live runs on the live version'}, one for each row of ${file.name}. Nothing starts until you press Start.`}
      backHref={back}
      actions={
        <LoadingButton onClick={() => void start()} isLoading={isPending} loadingText="Starting…" disabled={!checked} data-testid="batch-start">
          {checked ? `Start ${plural(checked.dry.rows, 'run')}` : 'Start runs'}
        </LoadingButton>
      }
    >
      <div data-testid="batch-check-page">
        <BatchCheck workflowId={workflowId} mode={mode} file={file} inputs={inputs} onChecked={setChecked} startError={startError} />
      </div>
    </PageLayout>
  );
}
