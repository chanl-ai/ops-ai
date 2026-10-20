'use client';

import * as React from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Plus, Radio } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { Note } from '@/components/shared/setting/note';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { EmbedDialog } from '@/components/deployments/widget-embed';
import { useAgent } from '@/hooks/queries';
import { useChannels } from '@/hooks/channel-queries';
import { useWidgetScriptUrl } from '@/hooks/widget-deployment-queries';
import { useListParams } from '@/hooks/use-list-params';
import type { ChannelType } from '@/lib/types/channels';

import { ChannelGallery } from './channel-gallery';
import { ChannelLanding } from './channel-landing';
import { ChannelTable } from './channel-table';
import { ChannelTabs } from './channel-tabs';
import { kindInfo } from './kinds';

/** Where a kind is set up; Channels links there instead of keeping a second form. */
const CONNECT: Partial<Record<ChannelType, { label: string; href: string; note?: string }>> = {
  email: { label: 'Connect a mailbox', href: '/channels/email/connect' },
  chat: { label: 'Embed on a page', href: '/channels/chat?embed=1', note: 'An embed serves one published agent. Embed on a page picks the agent; each agent’s Channels tab also lists its embeds, with their snippets and mint keys.' },
  api: { label: 'Open API keys', href: '/settings/api-keys', note: 'A system calls the API with a key from Settings › API keys; each key acts for its team.' },
};

/** Channels: one card per kind, then every connection with what it serves, its health and traffic (c-242). */
export function ChannelsHubPage() {
  const params = useSearchParams();
  const fromDeployments = params.get('from') === 'deployments';
  const movedAgent = params.get('agent');
  const list = useListParams<Record<string, never>>('name');
  const q = useChannels({ page: list.params.page, pageSize: list.params.pageSize, search: list.params.search });
  return (
    <PageLayout
      icon={Radio}
      title="Channels"
      description="Where work reaches the team’s agents and workflows: mailboxes, chat on the bank’s pages and the API"
      tabs={<ChannelTabs kinds={q.data?.kinds} />}
      actions={
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button data-testid="connect-channel">
              <Plus className="size-4" /> Connect channel
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            {(['email', 'chat', 'api'] as const).map((t) => {
              const k = kindInfo(t);
              const Icon = k.icon;
              return (
                <DropdownMenuItem key={t} asChild>
                  <Link href={CONNECT[t]!.href}>
                    <Icon className="size-4" /> {k.title}
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
      {q.isPending ? (
        <PageSkeleton statCards={3} tableRows={6} />
      ) : q.isError && !q.data ? (
        <QueryError what="channels" error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />
      ) : (
        <div className="flex flex-col gap-6 pb-16">
          {fromDeployments && <DeploymentsMovedNote agentId={movedAgent} />}
          <section className="flex flex-col gap-3" aria-labelledby="channel-types">
            <h2 id="channel-types" className="text-sm font-semibold">
              Channel types
            </h2>
            <ChannelGallery kinds={q.data.kinds} />
          </section>
          <section className="flex flex-col gap-3" aria-labelledby="all-connections">
            <h2 id="all-connections" className="text-sm font-semibold">
              All connections
            </h2>
            <ChannelTable rows={q.data.data} pagination={q.data.pagination} page={list.pagination} onPaginationChange={list.setPagination} onColumnFiltersChange={list.onColumnFiltersChange} loading={q.isFetching && q.isPlaceholderData} />
          </section>
        </div>
      )}
    </PageLayout>
  );
}

/** One kind's page: its landing card, then its connections; a kind coming soon says what it will do. */
export function ChannelKindPage({ type }: { type: ChannelType }) {
  const k = kindInfo(type);
  const list = useListParams<Record<string, never>>('name');
  const q = useChannels({ page: list.params.page, pageSize: list.params.pageSize, search: list.params.search, type: [type] });
  const summary = q.data?.kinds.find((s) => s.type === type);
  const connect = CONNECT[type];
  const rows = q.data?.data ?? [];
  // Embed on a page opens here, from this page's button or the hub's Connect channel menu (?embed=1).
  const scriptUrl = useWidgetScriptUrl();
  const [embedOpen, setEmbedOpen] = React.useState(() => type === 'chat' && typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('embed') === '1');
  const counted = rows.filter((c) => c.activity7d !== null);
  const week = counted.length ? counted.reduce((n, c) => n + (c.activity7d ?? 0), 0) : null;
  return (
    <PageLayout
      icon={k.icon}
      title={k.title}
      description={k.description}
      tabs={<ChannelTabs kinds={q.data?.kinds} />}
      actions={
        type === 'chat' ? (
          <Button onClick={() => setEmbedOpen(true)} data-testid="widget-embed-open">
            <Plus className="size-4" /> {connect!.label}
          </Button>
        ) : connect && summary?.built !== false ? (
          <Button asChild data-testid={type === 'email' ? 'connect-mailbox' : `connect-${type}`}>
            <Link href={connect.href}>
              <Plus className="size-4" /> {connect.label}
            </Link>
          </Button>
        ) : undefined
      }
    >
      {q.isPending ? (
        <PageSkeleton statCards={1} tableRows={4} />
      ) : q.isError && !q.data ? (
        <QueryError what={`${k.title.toLowerCase()} connections`} error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />
      ) : (
        <div className="flex flex-col gap-6 pb-16">
          <ChannelLanding type={type} summary={summary} week={week} sources={rows.map((c) => `channel:${c.id}`)} />
          {summary?.built ? (
            <>
              {connect?.note && <Note title="Where it is set up">{connect.note}</Note>}
              <ChannelTable rows={rows} oneKind={type} kind={k.title.toLowerCase()} pagination={q.data.pagination} page={list.pagination} onPaginationChange={list.setPagination} onColumnFiltersChange={list.onColumnFiltersChange} loading={q.isFetching && q.isPlaceholderData} />
            </>
          ) : (
            <Note title="Coming soon">Nothing to connect yet. When it ships, its connections list here with what each serves.</Note>
          )}
        </div>
      )}
      {type === 'chat' && <EmbedDialog scriptUrl={scriptUrl} open={embedOpen} onOpenChange={setEmbedOpen} />}
    </PageLayout>
  );
}

/** Where Deployments went, with a link to where an agent's versions are live: the one the old address named, or the list. */
function DeploymentsMovedNote({ agentId }: { agentId: string | null }) {
  return (
    <Note title="Deployments are now Channels">
      Every place an agent or workflow is reachable is a connection here, with what it serves and its version: the latest published one or a pinned one.{' '}
      {agentId ? (
        <AgentVersionsLink id={agentId} />
      ) : (
        <Link href="/agents" className="underline underline-offset-4" data-testid="deployments-moved-link">
          See where each agent’s versions are live
        </Link>
      )}
    </Note>
  );
}

function AgentVersionsLink({ id }: { id: string }) {
  const agent = useAgent(id);
  return (
    <Link href={`/agents/${encodeURIComponent(id)}?tab=channels`} className="underline underline-offset-4" data-testid="deployments-moved-link">
      See where {agent.data?.name ?? 'this agent'}’s versions are live
    </Link>
  );
}
