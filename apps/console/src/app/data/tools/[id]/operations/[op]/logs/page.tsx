'use client';

import { useParams } from 'next/navigation';
import { Wrench } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { ToolCallsView } from '@/components/tools/tool-calls-view';
import { ToolTabs } from '@/components/tools/tool-tabs';
import { useToolModule } from '@/hooks/tool-module-queries';

/** A tool's Logs tab: its calls through the gateway, the same list as Tool calls, fixed to this tool. */
export default function ToolLogsPage() {
  const params = useParams<{ id: string; op: string }>();
  const name = decodeURIComponent(params.op);
  const mod = useToolModule(params.id);
  if (mod.isPending) return <RecordSkeleton />;
  if (mod.isError)
    return (
      <PageLayout icon={Wrench} title={name} backHref="/data/tools">
        <QueryError what="this tool" onRetry={() => mod.refetch()} retrying={mod.isFetching} error={mod.error} />
      </PageLayout>
    );
  const op = mod.data.operations.find((o) => o.name === name);
  return (
    <PageLayout
      icon={Wrench}
      title={name}
      description={`${op?.description || `${mod.data.displayName} operation`} · ${mod.data.displayName}`}
      backHref={`/data/tools/${params.id}`}
      tabs={<ToolTabs moduleId={params.id} operation={name} />}
    >
      <ToolCallsView fixed={{ tool: [name], moduleId: [params.id] }} totals={false} emptyText={`No call of ${name} yet. Calls show here once an agent or a workflow runs it.`} />
    </PageLayout>
  );
}
