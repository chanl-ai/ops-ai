'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';

/** The old address of the person's accounts: they are Connectors (Mine) now. */
export default function OldMyConnectionsPage() {
  const router = useRouter();
  React.useEffect(() => {
    router.replace('/settings/account/connectors');
  }, [router]);
  return (
    <PageLayout title="Opening Connectors">
      <RecordSkeleton />
    </PageLayout>
  );
}
