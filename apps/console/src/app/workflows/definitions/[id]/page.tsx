'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { SearchX, Workflow } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { useCollapsedSidebar } from '@/components/shared/collapsed-sidebar';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { DefinitionEditor } from '@/components/workflows/definition-editor/definition-editor';
import { useCanBuild } from '@/hooks/me-queries';
import { useDefinition, useNodeTypes, usePublishDefinition, useRequestDefinitionPublish, useSetDefinitionPaused, useStartEngineRun, useValidateDefinition } from '@/hooks/engine-queries';
import { ApiError } from '@/lib/api';
import type { EngineDefinition } from '@/lib/types/engine';

const shortDigest = (digest: string) => digest.replace(/^sha256:/, '').slice(0, 8);

export default function WorkflowDefinitionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const definition = useDefinition(id);
  const nodeTypes = useNodeTypes();
  const canBuild = useCanBuild();
  const { mutateAsync: validateAsync } = useValidateDefinition();
  const { mutateAsync: publishAsync, isPending: publishing } = usePublishDefinition();
  const { mutateAsync: startAsync } = useStartEngineRun();
  const { mutateAsync: requestAsync } = useRequestDefinitionPublish(id);
  const { mutateAsync: pauseAsync, isPending: pausing } = useSetDefinitionPaused(id);
  const requestPublish = React.useCallback((note: string) => requestAsync({ note }), [requestAsync]);
  // The canvas needs the width; the sidebar comes back as it was when the person leaves the page.
  useCollapsedSidebar();

  const validate = React.useCallback((d: EngineDefinition) => validateAsync(d), [validateAsync]);
  const publish = React.useCallback((d: EngineDefinition) => publishAsync(d), [publishAsync]);
  const startRun = React.useCallback(
    async (input: Record<string, unknown>, mode: 'live' | 'test') => {
      const run = await startAsync({ workflowId: id, input, mode });
      router.push(`/workflows/runs/${run.runId}`);
    },
    [startAsync, id, router],
  );

  const view = definition.data;
  const notFound = definition.error instanceof ApiError && definition.error.status === 404;

  const header = {
    icon: Workflow,
    title: view?.name || view?.definition.name || id,
    description: view ? `Latest version ${view.version} · digest ${shortDigest(view.digest)}` : undefined,
    backHref: '/workflows',
    // The canvas fills what is left of the window under the header, so the page itself does not scroll.
    className: 'min-h-0 py-4 lg:py-4',
    contentClassName: 'flex min-h-0 flex-col',
  };

  if (view && nodeTypes.data && !definition.isError) {
    return (
      <DefinitionEditor
        key={view.workflowId}
        definition={view.definition}
        types={nodeTypes.data}
        validate={validate}
        publish={publish}
        publishing={publishing}
        startRun={startRun}
        lifecycle={view}
        requestPublish={requestPublish}
        setPaused={pauseAsync}
        pausing={pausing}
        readOnly={!canBuild}
        frame={({ actions, canvas }) => (
          <PageLayout {...header} actions={actions}>
            {canvas}
          </PageLayout>
        )}
      />
    );
  }

  return (
    <PageLayout {...header}>
      {definition.isPending || nodeTypes.isPending ? (
        <PageSkeleton statCards={0} tableRows={8} showToolbar />
      ) : notFound ? (
        <EmptyState icon={SearchX} title="No editable definition" description="This workflow has no version built from step types, so there is nothing to open here." action={{ label: 'Back to workflows', href: '/workflows' }} testId="definition-not-found" />
      ) : definition.isError ? (
        <QueryError what="this workflow" error={definition.error} onRetry={() => definition.refetch()} retrying={definition.isFetching} />
      ) : (
        nodeTypes.isError && <QueryError what="step types" error={nodeTypes.error} onRetry={() => nodeTypes.refetch()} retrying={nodeTypes.isFetching} />
      )}
    </PageLayout>
  );
}
