'use client';

import { notFound, useSearchParams } from 'next/navigation';
import { Play, Save, Workflow } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { useNodeTypes } from '@/hooks/engine-queries';

import { LargeCanvas, type Scene } from './large-canvas';
import { BROKEN_DEFINITION, EMPTY_DEFINITION, SAMPLE_DEFINITION } from './sample-definition';

const SCENES: Scene[] = ['empty', 'large', 'adding', 'step', 'trigger', 'error', 'phone'];

/**
 * The c-096 mock: the workflow editor on a full-width canvas, drawn over a sample definition with the server's real
 * step types and checks. `?scene=` picks the state a screenshot shows. Served by the dev server only, and not in the nav.
 */
export default function WorkflowLargeCanvasPage() {
  const params = useSearchParams();
  const types = useNodeTypes();
  if (process.env.NODE_ENV !== 'development') notFound();
  const asked = params.get('scene') as Scene | null;
  const scene: Scene = asked && SCENES.includes(asked) ? asked : 'large';
  const definition = scene === 'empty' ? EMPTY_DEFINITION : scene === 'error' ? BROKEN_DEFINITION : SAMPLE_DEFINITION;

  return (
    <PageLayout
      icon={Workflow}
      title={definition.name ?? definition.id}
      description={scene === 'empty' ? 'Not saved yet' : 'Version 3 · draft · live version 2'}
      backHref="/workflows"
      actions={
        <>
          <Button type="button" variant="outline">
            <Play /> Test run
          </Button>
          <Button type="button" disabled={scene === 'error' || scene === 'empty'}>
            <Save /> Save version
          </Button>
        </>
      }
      className="min-h-0 py-4 lg:py-4"
      contentClassName="flex min-h-0 flex-col"
    >
      {types.isPending ? (
        <PageSkeleton statCards={0} tableRows={6} />
      ) : types.isError ? (
        <QueryError what="step types" error={types.error} onRetry={() => types.refetch()} retrying={types.isFetching} />
      ) : (
        <LargeCanvas key={scene} initial={definition} types={types.data} scene={scene} />
      )}
    </PageLayout>
  );
}
