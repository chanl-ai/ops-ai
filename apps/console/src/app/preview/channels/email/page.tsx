'use client';

import * as React from 'react';
import Link from 'next/link';
import { Mail, Plus } from 'lucide-react';

import { EmptyState } from '@/components/shared/empty-state';
import { Button } from '@/components/ui/button';

import { ChannelLanding } from '../_parts/channel-landing';
import { AllConnections } from '../_parts/gallery';
import { ChannelsPageLayout } from '../_parts/layout';
import { MailboxSheet } from '../_parts/mailbox-sheet';
import { ROOT, type Connection } from '../_sample/data';
import { useConnections } from '../_sample/store';

/** The workspace's mailboxes. A row opens its settings drawer; Connect a mailbox opens the connect page. */
export default function EmailChannel() {
  const all = useConnections();
  const mailboxes = all.filter((c) => c.type === 'email');
  const [openId, setOpenId] = React.useState<string | null>(null);
  const open = mailboxes.find((c) => c.id === openId) ?? null;
  return (
    <ChannelsPageLayout
      title="Email mailboxes"
      description="Mailboxes whose new mail starts workflows, and the sender each one replies with"
      actions={
        <Button asChild data-testid="connect-mailbox">
          <Link href={`${ROOT}/email/connect`}>
            <Plus className="size-4" /> Connect a mailbox
          </Link>
        </Button>
      }
    >
      <ChannelLanding type="email" connections={all} />
      {mailboxes.length ? (
        <AllConnections connections={mailboxes} onOpenMailbox={(c: Connection) => setOpenId(c.id)} oneKind />
      ) : (
        <EmptyState icon={Mail} title="No mailbox connected" description="Connect one, then pick it in a workflow's Email received trigger." action={{ label: 'Connect a mailbox', href: `${ROOT}/email/connect` }} />
      )}
      <MailboxSheet mailbox={open} onOpenChange={(o) => !o && setOpenId(null)} />
    </ChannelsPageLayout>
  );
}
