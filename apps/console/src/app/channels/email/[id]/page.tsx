'use client';

import { use } from 'react';
import { Mail } from 'lucide-react';

import { MailboxSettingsForm, MailboxStatus, MailboxWorkflows } from '@/components/channels/mailbox-panels';
import { PageLayout } from '@/components/page-layout';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { useMailbox } from '@/hooks/channels-queries';

/** One mailbox: its status, the workflows bound to it, and its settings with a test, pause and resume. */
export default function MailboxPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const mailbox = useMailbox(id);
  if (mailbox.isLoading) return <RecordSkeleton />;
  if (mailbox.isError && !mailbox.data)
    return (
      <PageLayout icon={Mail} title="Mailbox" description="Channels › Email" backHref="/channels/email">
        <QueryError what="the mailbox" onRetry={() => void mailbox.refetch()} error={mailbox.error} back={{ label: 'Back to mailboxes', href: '/channels/email' }} />
      </PageLayout>
    );
  const m = mailbox.data!;
  return (
    <PageLayout icon={Mail} title={m.name} description={m.address} backHref="/channels/email">
      <div className="flex flex-col gap-6 pb-16" data-testid="mailbox-page">
        <MailboxStatus mailbox={m} />
        <MailboxWorkflows mailbox={m} />
        <MailboxSettingsForm mailbox={m} />
      </div>
    </PageLayout>
  );
}
