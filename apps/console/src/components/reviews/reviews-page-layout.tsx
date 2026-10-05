'use client';

import { UserCheck } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { RouteTabs } from '@/components/shared/route-tabs';

/** Shared header for the Reviews section so Queue and Gate policies read as one page with two tabs. */
export function ReviewsPageLayout({ actions, children }: { actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <PageLayout
      icon={UserCheck}
      title="Reviews"
      description="Agent actions and workflow publishes waiting for a person"
      actions={actions}
      tabs={
        <RouteTabs
          tabs={[
            { href: '/reviews', label: 'Queue' },
            { href: '/reviews/policies', label: 'Gate policies' },
          ]}
        />
      }
    >
      {children}
    </PageLayout>
  );
}
