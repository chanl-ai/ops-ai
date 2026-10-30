'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Workflow } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { useCollapsedSidebar } from '@/components/shared/collapsed-sidebar';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { DefinitionEditor } from '@/components/workflows/definition-editor/definition-editor';
import { useCan, useCanBuild } from '@/hooks/me-queries';
import { useDefinition, useNodeTypes, usePublishDefinition, useRequestDefinitionPublish, useSetDefinitionPaused, useStartEngineRun, useStartWorkflow, useValidateDefinition } from '@/hooks/engine-queries';
import type { EngineDefinition } from '@/lib/types/engine';

const shortDigest = (digest: string) => digest.replace(/^sha256:/, '').slice(0, 8);

export default function WorkflowDefinitionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const definition = useDefinition(id);
  const nodeTypes = useNodeTypes();
  const canBuild = useCanBuild();
  const canPublish = useCan('workflows', 'publish');
  const { mutateAsync: validateAsync } = useValidateDefinition();
  const { mutateAsync: publishAsync, isPending: publishing } = usePublishDefinition();
  const { mutateAsync: startAsync } = useStartEngineRun();
  const { mutateAsync: startByFormAsync } = useStartWorkflow();
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
  const startByHand = React.useCallback(
    async (values: Record<string, unknown>, mode: 'live' | 'test') => {
      const run = await startByFormAsync({ workflowId: id, values, mode });
      router.push(`/workflows/runs/${run.runId}`);
    },
    [startByFormAsync, id, router],
  );

  const view = definition.data;

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
        startByHand={startByHand}
        lifecycle={view}
        requestPublish={requestPublish}
        setPaused={pauseAsync}
        pausing={pausing}
        readOnly={!canBuild}
        canPublish={canPublish}
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
      ) : definition.isError ? (
        <QueryError what="this workflow" error={definition.error} back={{ label: 'Back to workflows', href: '/workflows' }} onRetry={() => definition.refetch()} retrying={definition.isFetching} />
      ) : (
        nodeTypes.isError && <QueryError what="step types" error={nodeTypes.error} onRetry={() => nodeTypes.refetch()} retrying={nodeTypes.isFetching} />
      )}
    </PageLayout>
  );
}
