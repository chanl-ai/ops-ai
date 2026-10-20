'use client';

import * as React from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Plus } from 'lucide-react';

import { Note } from '@/components/shared/setting/note';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';

import { AllConnections, ChannelGallery, TYPE_ICON } from './_parts/gallery';
import { ChannelsPageLayout } from './_parts/layout';
import { MailboxSheet } from './_parts/mailbox-sheet';
import { CHANNEL_TYPES, ROOT, type Connection } from './_sample/data';
import { useConnections } from './_sample/store';

/** The workspace's channels: one card per kind, then every connection with its status, last activity and workflows. */
export default function ChannelsHome() {
  const connections = useConnections();
  const fromDeployments = useSearchParams().get('from') === 'deployments';
  const [openId, setOpenId] = React.useState<string | null>(null);
  const open = connections.find((c) => c.id === openId) ?? null;
  return (
    <ChannelsPageLayout
      title="Channels"
      description="Where work reaches the workspace's workflows: mailboxes, chat on the bank's pages and the API"
      back={false}
      actions={
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button data-testid="connect-channel">
              <Plus className="size-4" /> Connect channel
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            <DropdownMenuItem asChild>
              <Link href={`${ROOT}/email/connect`}>
                <TYPE_ICON.email className="size-4" /> Email mailbox
              </Link>
            </DropdownMenuItem>
            {CHANNEL_TYPES.filter((t) => t.built && t.type !== 'email').map((t) => {
              const Icon = TYPE_ICON[t.type];
              return (
                <DropdownMenuItem key={t.type} asChild>
                  <Link href={t.href}>
                    <Icon className="size-4" /> {t.title}
                  </Link>
                </DropdownMenuItem>
              );
            })}
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">MCP, Slack and Teams are coming soon</DropdownMenuLabel>
          </DropdownMenuContent>
        </DropdownMenu>
      }
    >
      {fromDeployments && (
      <Note title="Deployments are now Channels">
        Every place an agent or workflow is reachable is a connection here, with what it serves and the version: the latest published one or a pinned one.{' '}
        <Link href={`${ROOT}/agent`} className="underline underline-offset-4">
          See where Advisor’s Helper’s versions are live
        </Link>
      </Note>
      )}
      <section className="flex flex-col gap-3" aria-labelledby="channel-types">
        <h2 id="channel-types" className="text-sm font-semibold">
          Channel types
        </h2>
        <ChannelGallery connections={connections} />
      </section>
      <section className="flex flex-col gap-3" aria-labelledby="all-connections">
        <h2 id="all-connections" className="text-sm font-semibold">
          All connections
        </h2>
        <AllConnections connections={connections} onOpenMailbox={(c: Connection) => setOpenId(c.id)} />
      </section>
      <MailboxSheet mailbox={open} onOpenChange={(o) => !o && setOpenId(null)} />
    </ChannelsPageLayout>
  );
}
