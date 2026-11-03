'use client';

import { useSearchParams } from 'next/navigation';
import { ScrollText } from 'lucide-react';

import { AppsTabs } from '@/components/connections/apps-tabs';
import { PageLayout } from '@/components/page-layout';
import { ToolCallsView } from '@/components/tools/tool-calls-view';

export default function ToolCallsPage() {
  const search = useSearchParams();
  const q = search.get('q');
  const run = search.get('run');
  return (
    <PageLayout switcher icon={ScrollText} tabs={<AppsTabs />} title="Tool calls" description={run ? `Every gateway call behind run ${run}, with its approval and policy` : 'Every tool and model call through the data and AI gateways, with its approval and policy'}>
      <ToolCallsView run={run} q={q} />
    </PageLayout>
  );
}
