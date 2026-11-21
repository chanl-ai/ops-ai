'use client';

import { useParams } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { workflowHeader } from '@/components/workflows/definition-editor/editor-shell';
import { VersionsList } from '@/components/workflows/definition-editor/versions-list';
import { useDefinition } from '@/hooks/engine-queries';

/** The Versions tab: every version of the workflow and its working copy, each compared with the live one or restored. */
export default function WorkflowVersionsPage() {
  const { id } = useParams<{ id: string }>();
  const definition = useDefinition(id);
  return (
    <PageLayout {...workflowHeader(id, definition.data)}>
      {definition.isPending ? (
        <PageSkeleton statCards={0} tableRows={5} />
      ) : definition.isError ? (
        <QueryError what="this workflow" error={definition.error} back={{ label: 'Back to workflows', href: '/build/workflows' }} onRetry={() => definition.refetch()} retrying={definition.isFetching} />
      ) : (
        <VersionsList view={definition.data} />
      )}
    </PageLayout>
  );
}
