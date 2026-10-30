'use client';

import * as React from 'react';
import { History } from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { useDefinition } from '@/hooks/engine-queries';

/**
 * The old workflow address, `/workflows/<id>`, which links across the console and people's bookmarks still use. A
 * workflow the runner holds opens its own page; any other was built on the earlier workflow engine, which the console
 * no longer shows, so the page says so and points back to Workflows.
 */
export default function OldWorkflowAddress() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const definition = useDefinition(id);
  const gone = (definition.error as { status?: number } | null)?.status === 404;
  React.useEffect(() => {
    if (definition.data) router.replace(`/workflows/definitions/${encodeURIComponent(id)}`);
  }, [definition.data, id, router]);
  return (
    <PageLayout icon={History} title="Workflow" backHref="/workflows">
      {gone ? (
        <EmptyState
          icon={History}
          title="This workflow is no longer available"
          description="It was built on an earlier kind of workflow that the console no longer shows. Every current workflow is on the Workflows page."
          action={{ label: 'Open Workflows', href: '/workflows' }}
          testId="workflow-no-longer-available"
        />
      ) : definition.isError ? (
        <QueryError what="the workflow" onRetry={() => definition.refetch()} error={definition.error} retrying={definition.isFetching} />
      ) : (
        <PageSkeleton statCards={0} tableRows={4} />
      )}
    </PageLayout>
  );
}
