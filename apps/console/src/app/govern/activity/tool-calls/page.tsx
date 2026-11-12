'use client';

import { useSearchParams } from 'next/navigation';
import { ScrollText } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { ToolCallsView } from '@/components/tools/tool-calls-view';
import { ToolsTabs } from '@/components/tools/tools-tabs';

export default function ToolCallsPage() {
  const search = useSearchParams();
  const q = search.get('q');
  const run = search.get('run');
  return (
    <PageLayout switcher icon={ScrollText} title="Tool calls" description={run ? `Every call behind run ${run}, with its approval and policy` : 'Every tool and model call, with its approval and policy'}>
      <div className="flex flex-col gap-4">
        <ToolsTabs />
        <ToolCallsView run={run} q={q} />
      </div>
    </PageLayout>
  );
}
