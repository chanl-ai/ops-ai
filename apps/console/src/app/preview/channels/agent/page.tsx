'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { Activity, Bot, MessagesSquare, Route } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { Note } from '@/components/shared/setting/note';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemMedia, ItemTitle } from '@/components/ui/item';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { facetFilterFn } from '@/hooks/use-list-params';
import { plural, relativeTime } from '@/lib/format';

import { TYPE_ICON, TYPE_LABEL } from '../_parts/gallery';
import { ConnectionStatusDot } from '../_parts/layout';
import { ROOT, serveOption, type ConnectionStatus } from '../_sample/data';
import { useConnections } from '../_sample/store';

const AGENT = { id: 'ag_advisor', name: 'Advisor’s Helper' };

/** One place the agent answers: an embed or another channel connection, or a workflow step that calls it. */
interface LiveRow {
  id: string;
  name: string;
  detail: string;
  channel: string;
  icon: React.ComponentType<{ className?: string }>;
  version: number;
  pinned: boolean;
  behind: number;
  status: ConnectionStatus;
  traffic24h: number;
  errors24h: number;
  lastActivityAt?: string;
  href: string;
  rowTestId: string;
}

// The one workflow that calls the agent in the sample; a workflow step always pins a version.
const WORKFLOW_ROWS = [{ id: 'wf_customer_summary', name: 'Customer summary', detail: 'Summarise the customer step', version: 5, traffic24h: 64, errors24h: 0, lastActivityAt: new Date(Date.now() - 18 * 60_000).toISOString() }];

const COLUMNS: ColumnDef<LiveRow>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Where it answers" />,
    cell: ({ row }) => {
      const Icon = row.original.icon;
      return (
        <Link href={row.original.href} className="flex min-w-0 items-center gap-2 underline-offset-4 hover:underline">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0">
            <span className="block truncate font-medium">{row.original.name}</span>
            <span className="block truncate text-xs text-muted-foreground">{row.original.detail}</span>
          </span>
        </Link>
      );
    },
    enableHiding: false,
  },
  { accessorKey: 'channel', header: 'Channel', filterFn: facetFilterFn },
  {
    id: 'version',
    accessorFn: (r) => `v${r.version}`,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Version live" />,
    cell: ({ row }) => (
      <span className="flex flex-wrap items-center gap-1.5 whitespace-nowrap">
        <span className="font-medium tabular-nums">v{row.original.version}</span>
        <span className="text-xs text-muted-foreground">{row.original.pinned ? 'pinned' : 'latest'}</span>
        {row.original.behind > 0 && <Badge variant="outline" className="border-warning/40 text-warning-text">{plural(row.original.behind, 'behind', 'behind')}</Badge>}
      </span>
    ),
    filterFn: facetFilterFn,
  },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => <ConnectionStatusDot status={row.original.status} at={row.original.lastActivityAt} />, filterFn: facetFilterFn },
  {
    accessorKey: 'traffic24h',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Traffic · 24h" />,
    cell: ({ row }) => (
      <span className="whitespace-nowrap tabular-nums">
        {row.original.traffic24h.toLocaleString('en-CA')}
        {row.original.errors24h > 0 && <span className="ml-1.5 text-destructive">{plural(row.original.errors24h, 'error', 'errors')}</span>}
      </span>
    ),
  },
  { accessorKey: 'lastActivityAt', header: 'Last activity', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.lastActivityAt ? relativeTime(row.original.lastActivityAt) : 'None yet'}</span> },
];

/**
 * The agent page's Channels tab, restored as a table: every place the agent answers with the version live there and its
 * traffic, from the same connections the Channels hub lists. Versions are the agent's; a connection only picks one.
 */
export default function AgentChannelsMock() {
  const connections = useConnections();
  const latest = serveOption({ kind: 'agent', id: AGENT.id, version: 'latest' })!.versions[0];
  const rows: LiveRow[] = React.useMemo(() => {
    const versions = serveOption({ kind: 'agent', id: AGENT.id, version: 'latest' })!.versions;
    const fromChannels = connections
      .filter((c) => c.serves.kind === 'agent' && c.serves.id === AGENT.id)
      .map((c) => {
        const version = c.serves.version === 'latest' ? versions[0] : c.serves.version;
        return { id: c.id, name: c.name, detail: c.detail, channel: TYPE_LABEL[c.type], icon: TYPE_ICON[c.type], version, pinned: c.serves.version !== 'latest', behind: versions.indexOf(version), status: c.status, traffic24h: c.traffic24h, errors24h: c.errors24h, lastActivityAt: c.lastActivityAt, href: `${ROOT}/${c.type}`, rowTestId: `agent-live-${c.id}` };
      });
    const fromWorkflows = WORKFLOW_ROWS.map((w) => ({ ...w, channel: 'Workflow step', icon: Route, pinned: true, behind: versions.indexOf(w.version), status: 'connected' as const, href: '/workflows', rowTestId: `agent-live-${w.id}` }));
    return [...fromChannels, ...fromWorkflows];
  }, [connections]);
  const byVersion = rows.reduce<Record<number, number>>((m, r) => ((m[r.version] = (m[r.version] ?? 0) + 1), m), {});
  const week = connections.filter((c) => c.serves.kind === 'agent' && c.serves.id === AGENT.id).reduce((n, c) => n + c.activity7d, 0);
  const channels = [...new Set(rows.map((r) => r.channel))].map((c) => ({ label: c, value: c }));

  return (
    <PageLayout
      icon={Bot}
      title={AGENT.name}
      description="Answers an advisor’s questions about the customer in front of them and the bank’s products"
      backHref={ROOT}
      tabs={
        <Tabs value="channels">
          <TabsList>
            <TabsTrigger value="settings" disabled>
              Settings
            </TabsTrigger>
            <TabsTrigger value="channels">Channels</TabsTrigger>
          </TabsList>
        </Tabs>
      }
    >
      <div className="flex flex-col gap-6 pb-16">
        <Note tone="sample" title="Design mock">
          The agent page’s Channels tab with sample data. A connection is changed on the Channels page; this tab shows where each version is live.
        </Note>
        <Card className="gap-3">
          <CardHeader>
            <CardTitle>Versions live</CardTitle>
            <CardDescription>Published v{latest}. A connection follows the latest published version or pins one; publishing never moves a pinned one.</CardDescription>
          </CardHeader>
          <CardContent>
            <ItemGroup className="gap-2">
              {Object.keys(byVersion)
                .map(Number)
                .sort((a, b) => b - a)
                .map((v) => (
                  <Item key={v} variant="outline" size="sm" data-testid={`agent-version-${v}`}>
                    <ItemContent>
                      <ItemTitle>
                        v{v} {v === latest ? <Badge variant="secondary">Latest</Badge> : <Badge variant="outline">{plural(latest - v, 'version behind', 'versions behind')}</Badge>}
                      </ItemTitle>
                      <ItemDescription>Live in {plural(byVersion[v], 'place', 'places')}: {rows.filter((r) => r.version === v).map((r) => r.name).join(', ')}</ItemDescription>
                    </ItemContent>
                  </Item>
                ))}
            </ItemGroup>
          </CardContent>
        </Card>
        <Item variant="outline">
          <ItemMedia variant="icon">
            <MessagesSquare />
          </ItemMedia>
          <ItemContent>
            <ItemTitle>Available in chat</ItemTitle>
            <ItemDescription>Everyone in Operations can chat with the latest published version.</ItemDescription>
          </ItemContent>
          <ItemActions>
            <Button asChild variant="outline" size="sm">
              <Link href={`${ROOT}/activity?agent=${AGENT.id}`}>
                <Activity className="size-4" /> View activity · {week.toLocaleString('en-CA')}
              </Link>
            </Button>
          </ItemActions>
        </Item>
        <DataTableWithViews
          columns={COLUMNS}
          data={rows}
          getRowId={(r) => r.id}
          searchColumn="name"
          searchPlaceholder="Search where it answers…"
          hideViewSwitcher
          filters={[
            { column: 'channel', title: 'Channel', options: channels },
            { column: 'version', title: 'Version', options: Object.keys(byVersion).map((v) => ({ label: `v${v}`, value: `v${v}` })) },
            { column: 'status', title: 'Status', options: [ { label: 'Connected', value: 'connected' }, { label: 'Needs attention', value: 'attention' }, { label: 'Paused', value: 'paused' } ] },
          ]}
        />
      </div>
    </PageLayout>
  );
}
