'use client';

import { Mail } from 'lucide-react';
import { useRouter } from 'next/navigation';

import { ConnectMailbox } from '@/components/channels/connect-mailbox';
import { PageLayout } from '@/components/page-layout';

/** The connect form's page shell; the trigger sheet opens the same form as a dialog. */
export default function ConnectMailboxPage() {
  const router = useRouter();
  return (
    <PageLayout icon={Mail} title="Connect a mailbox" description="Pick the provider, point it at a folder and test it" backHref="/channels/email">
      <div className="mx-auto flex max-w-3xl flex-col gap-6 pb-16">
        <ConnectMailbox shell="page" onConnected={(m) => router.push(`/channels/email/${encodeURIComponent(m.id)}`)} />
      </div>
    </PageLayout>
  );
}
