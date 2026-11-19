'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';

import { PageLayout } from '@/components/page-layout';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { useSystemCard } from '@/hooks/systems-queries';
import { appPageHref } from '@/lib/app-links';

/**
 * The old connection page's address: it lands on the app's own page. A plugin's account opens its plugin's app,
 * an app connected by name opens itself; the card named by that id is the one place that says which app holds the account.
 */
export default function OldConnectionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const connectionId = decodeURIComponent(id);
  const card = useSystemCard(connectionId);
  React.useEffect(() => {
    if (card.isPending) return;
    router.replace(card.data ? appPageHref(card.data.id) : '/data/connectors');
  }, [card.isPending, card.data, router]);
  return (
    <PageLayout title="Opening the app">
      <RecordSkeleton />
    </PageLayout>
  );
}
