'use client';

import * as React from 'react';
import { use } from 'react';
import { Mail, Settings } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { Button } from '@/components/ui/button';

import { ChannelsPageLayout } from '../../_parts/layout';
import { MailboxSheet, MailboxStatus, MailboxWorkflows } from '../../_parts/mailbox-sheet';
import { ROOT } from '../../_sample/data';
import { useConnection } from '../../_sample/store';

/** One mailbox: its status, the last message it received and the workflows bound to it. Settings open in the drawer. */
export default function MailboxPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const mailbox = useConnection(id);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  if (!mailbox || mailbox.type !== 'email')
    return (
      <ChannelsPageLayout back={`${ROOT}/email`} title="Mailbox not found" description="It may have been removed">
        <EmptyState icon={Mail} title="Mailbox not found" description="No mailbox in this workspace has that id." action={{ label: 'Back to mailboxes', href: `${ROOT}/email` }} />
      </ChannelsPageLayout>
    );
  return (
    <ChannelsPageLayout
      back={`${ROOT}/email`}
      title={mailbox.name}
      description={mailbox.detail}
      actions={
        <Button variant="outline" onClick={() => setSettingsOpen(true)} data-testid="mailbox-settings">
          <Settings className="size-4" /> Settings
        </Button>
      }
    >
      <MailboxStatus mailbox={mailbox} />
      <MailboxWorkflows mailbox={mailbox} />
      <MailboxSheet mailbox={settingsOpen ? mailbox : null} onOpenChange={setSettingsOpen} />
    </ChannelsPageLayout>
  );
}
