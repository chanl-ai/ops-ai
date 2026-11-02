'use client';

import * as React from 'react';
import { useRouter, useSearchParams } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';

/**
 * The old address of the call log (c-617): it lives under Apps › Tools now. The query carries through, so a link that
 * opened one call (?id=) or a filtered list (?q=, ?run=) opens the same thing there.
 */
export default function OldToolCallsPage() {
  const router = useRouter();
  const search = useSearchParams();
  React.useEffect(() => {
    const q = search.toString();
    router.replace(`/tools/calls${q ? `?${q}` : ''}`);
  }, [router, search]);
  return (
    <PageLayout title="Opening Tool calls">
      <RecordSkeleton />
    </PageLayout>
  );
}
