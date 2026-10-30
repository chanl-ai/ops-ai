'use client';

import { Brain } from 'lucide-react';

import { MemoryList } from '@/components/memory/memory-list';
import { PageLayout } from '@/components/page-layout';

/** My account › Memory: what agents remember about the signed-in person, to correct, forget or export (c-206). */
export default function AccountMemoryPage() {
  return (
    <PageLayout icon={Brain} title="My memory" description="What agents remember about you">
      <div data-testid="account-memory">
        <MemoryList />
      </div>
    </PageLayout>
  );
}
