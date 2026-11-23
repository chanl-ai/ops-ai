'use client';

import { useParams, useRouter } from 'next/navigation';
import { UserRound } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { MyAppActions } from '@/components/connections/my-app-actions';
import { MyAppDetails } from '@/components/connections/my-app-details';
import { useMyConnector } from '@/hooks/connections-queries';

const BACK = { label: 'My apps', href: '/work/apps' };

/**
 * One app on the person's own page (the card on My apps opens it): their sign-in, what the app can do as them and where
 * it is used. The server answers with this app's row alone (GET /v1/me/connections?app=<id>).
 */
export default function MyAppPage() {
  const { id } = useParams<{ id: string }>();
  const appId = decodeURIComponent(id);
  const router = useRouter();
  const query = useMyConnector(appId);
  const c = query.data;

  if (query.isPending)
    return (
      <PageLayout icon={UserRound} title="App" backHref="/work/apps">
        <PageSkeleton statCards={0} tableRows={4} />
      </PageLayout>
    );
  if (query.isError || !c)
    return (
      <PageLayout icon={UserRound} title="App" backHref="/work/apps">
        <QueryError
          what="this app"
          // No row back means the person has no such app: say so as a missing page, with the way back.
          error={query.isError ? query.error : { status: 404 }}
          onRetry={() => void query.refetch()}
          retrying={query.isFetching}
          back={BACK}
          testId="my-app-error"
        />
      </PageLayout>
    );
  return (
    <PageLayout icon={UserRound} title={c.name} description={c.canDo} backHref="/work/apps">
      <MyAppActions onDisconnected={() => router.push('/work/apps')}>{(controls) => <MyAppDetails c={c} controls={controls} />}</MyAppActions>
    </PageLayout>
  );
}
