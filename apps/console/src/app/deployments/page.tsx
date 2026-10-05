'use client';

import * as React from 'react';
import { Plus, Rocket } from 'lucide-react';

import { DeploymentsTable } from '@/components/deployments/deployments-table';
import { PageLayout } from '@/components/page-layout';
import { Button } from '@/components/ui/button';
import { useCreateParam } from '@/hooks/use-create-param';

export default function DeploymentsPage() {
  const [createOpen, setCreateOpen, variant] = useCreateParam();
  // `?create=1` opens the create dialog, so other pages (an empty Cases list) can link straight to it.
  React.useEffect(() => {
    if (new URLSearchParams(window.location.search).get('create') === '1') setCreateOpen(true);
  }, []);
  return (
    <PageLayout
      icon={Rocket}
      title="Deployments"
      description="Where each published workflow is reachable: chat widget, API or email"
      actions={
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> New deployment
        </Button>
      }
    >
      <DeploymentsTable createOpen={createOpen} onCreateOpenChange={setCreateOpen} createChannel={variant === 'email' ? 'email' : undefined} />
    </PageLayout>
  );
}
