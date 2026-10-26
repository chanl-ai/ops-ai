'use client';

import { UserCheck } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';

/** Shared header for the Human Tasks queue. Gate policies live under Govern > Policies in the settings tree. */
export function ReviewsPageLayout({
  actions,
  children,
  title = 'Human Tasks',
  description = 'Agent actions and workflow publishes waiting for a person',
  backHref,
}: {
  actions?: React.ReactNode;
  children: React.ReactNode;
  title?: string;
  description?: string;
  backHref?: string;
}) {
  return (
    <PageLayout icon={UserCheck} title={title} description={description} actions={actions} backHref={backHref}>
      {children}
    </PageLayout>
  );
}
