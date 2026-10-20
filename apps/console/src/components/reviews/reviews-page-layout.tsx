'use client';

import { UserCheck } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';

/** Shared header for the Human Tasks queue. Gate policies live under Govern > Policies in the settings tree. */
export function ReviewsPageLayout({ actions, children }: { actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <PageLayout icon={UserCheck} title="Human Tasks" description="Agent actions and workflow publishes waiting for a person" actions={actions}>
      {children}
    </PageLayout>
  );
}
