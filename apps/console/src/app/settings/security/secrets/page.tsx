'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';

/** The old address of the team's secrets: they live in Apps › Credentials, on its Secrets tab. */
export default function OldSecretsPage() {
  const router = useRouter();
  React.useEffect(() => {
    router.replace('/data/secrets?tab=secrets');
  }, [router]);
  return (
    <PageLayout title="Opening Credentials">
      <RecordSkeleton />
    </PageLayout>
  );
}
