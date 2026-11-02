'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';

/** The old address of the person's accounts (c-617): they live in the Apps menu as My accounts now. */
export default function OldMyConnectionsPage() {
  const router = useRouter();
  React.useEffect(() => {
    router.replace('/integrations/my-accounts');
  }, [router]);
  return (
    <PageLayout title="Opening My accounts">
      <RecordSkeleton />
    </PageLayout>
  );
}
