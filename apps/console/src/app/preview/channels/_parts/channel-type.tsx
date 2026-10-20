'use client';

import Link from 'next/link';

import { Note } from '@/components/shared/setting/note';
import { Button } from '@/components/ui/button';

import { CHANNEL_TYPES, type ChannelType } from '../_sample/data';
import { useConnections } from '../_sample/store';
import { ChannelLanding } from './channel-landing';
import { AllConnections } from './gallery';
import { ChannelsPageLayout } from './layout';

/** Where each built kind is made today, so the channels page links to it instead of building a second form. */
const MADE_ON: Partial<Record<ChannelType, { text: string; href: string; label: string }>> = {
  chat: { text: 'An embed is made for one published agent, on its Channels tab, and pins the version it serves.', href: '/preview/channels/agent', label: 'Open Advisor’s Helper’s Channels tab' },
  api: { text: 'A system calls the API with a key from Team › API keys; each key names the runs it may start.', href: '/preview/settings/team/api-keys', label: 'Open API keys' },
};

/** A channel kind's page: its landing card, then its connections when a service serves it. */
export function ChannelTypePageLayout({ type }: { type: ChannelType }) {
  const info = CHANNEL_TYPES.find((t) => t.type === type)!;
  const connections = useConnections();
  const rows = connections.filter((c) => c.type === type);
  const made = MADE_ON[type];
  return (
    <ChannelsPageLayout title={info.title} description={info.description}>
      <ChannelLanding
        type={type}
        connections={connections}
        action={
          made && (
            <Button asChild size="sm">
              <Link href={made.href}>{made.label}</Link>
            </Button>
          )
        }
      />
      {info.built ? (
        <>
          {made && <Note title="Where it is made">{made.text}</Note>}
          <AllConnections connections={rows} onOpenMailbox={() => undefined} linkOthers={false} oneKind />
        </>
      ) : (
        <Note title="Coming soon">Nothing to connect yet. When it ships, its connections list here with what each serves.</Note>
      )}
    </ChannelsPageLayout>
  );
}
