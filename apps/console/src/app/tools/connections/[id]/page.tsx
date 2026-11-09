'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { useSystems } from '@/hooks/systems-queries';
import { appPageHref } from '@/lib/app-links';

/**
 * The old connection page's address: it lands on the app's own page. A plugin's account opens its plugin's app,
 * an app connected by name opens itself; the card list is the one place that says which app holds the account.
 */
export default function OldConnectionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const systems = useSystems();
  const connectionId = decodeURIComponent(id);
  React.useEffect(() => {
    if (systems.isPending) return;
    const card = (systems.data ?? []).find((c) => c.id === connectionId || c.connectionId === connectionId);
    router.replace(card ? appPageHref(card.id) : '/integrations');
  }, [systems.isPending, systems.data, connectionId, router]);
  return (
    <PageLayout title="Opening the app">
      <RecordSkeleton />
    </PageLayout>
  );
}
