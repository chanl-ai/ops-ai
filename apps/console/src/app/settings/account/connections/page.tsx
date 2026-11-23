'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';

/** The old address of the person's accounts: they are My apps now. */
export default function OldMyConnectionsPage() {
  const router = useRouter();
  React.useEffect(() => {
    router.replace('/work/apps');
  }, [router]);
  return (
    <PageLayout title="Opening My apps">
      <RecordSkeleton />
    </PageLayout>
  );
}
