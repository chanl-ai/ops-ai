'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { CheckCircle2, Plug, Plus, XCircle } from 'lucide-react';

import { ChannelTabs } from '@/components/channels/hub/channel-tabs';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BuilderOnly } from '@/components/shared/builder-only';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useChannels } from '@/hooks/channel-queries';
import { useMcpLinks } from '@/hooks/mcp-link-queries';
import { plural, relativeTime } from '@/lib/format';
import type { McpLink } from '@/lib/types/mcp-links';

import { NewLinkDialog } from './new-link-dialog';

type Row = McpLink & { href: string; onRowClick: () => void; rowTestId: string };

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: 'name',
    header: 'MCP link',
    cell: ({ row }) => (
      <span className="flex min-w-0 flex-col">
        <span className="truncate font-medium">{row.original.name}</span>
        <span className="text-xs text-muted-foreground">{plural(row.original.toolCount, 'tool')}</span>
      </span>
    ),
  },
  {
    id: 'environment',
    header: 'Environment',
    cell: ({ row }) => (
      <span className="flex flex-wrap gap-1">
        <Badge variant="outline">Test</Badge>
        {row.original.paused && (
          <Badge variant="outline" className="border-warning/40 text-warning-text">
            Paused
          </Badge>
        )}
      </span>
    ),
  },
  { id: 'who', header: 'Who can connect', cell: () => <span className="text-sm">Sign-in and keys</span> },
  {
    id: 'last',
    header: 'Last call',
    cell: ({ row }) => {
      const last = row.original.lastCall;
      if (!last) return <span className="text-sm text-muted-foreground">No calls yet</span>;
      const ok = last.outcome === 'ok';
      const Icon = ok ? CheckCircle2 : XCircle;
      return (
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground" data-testid="mcp-link-last-call">
          <Icon className={ok ? 'size-3.5 text-success' : 'size-3.5 text-destructive'} aria-hidden />
          {relativeTime(last.at)} · {ok ? (last.client ?? 'an assistant') : last.outcome}
        </span>
      );
    },
  },
];

/** Channels › MCP: the team's links. Admins make new ones; every member opens a link to see how to connect. */
export function McpLinksPage() {
  const router = useRouter();
  const kinds = useChannels({ page: 1, pageSize: 1, search: '' });
  const q = useMcpLinks();
  const [open, setOpen] = React.useState(false);
  const rows: Row[] = (q.data ?? []).map((l) => {
    const href = `/build/channels/mcp/${encodeURIComponent(l.id)}`;
    return { ...l, href, onRowClick: () => router.push(href), rowTestId: `mcp-link-row-${l.slug}` };
  });
  return (
    <PageLayout
      icon={Plug}
      title="Channels"
      description="Where people and other systems reach your agents and tools"
      tabs={<ChannelTabs kinds={kinds.data?.kinds} />}
      actions={
        <BuilderOnly area="deployments">
          <Button onClick={() => setOpen(true)} data-testid="mcp-new-link-open">
            <Plus className="size-4" /> New MCP link
          </Button>
        </BuilderOnly>
      }
    >
      {q.isPending ? (
        <PageSkeleton tableRows={4} />
      ) : q.isError && !q.data ? (
        <QueryError what="the MCP links" error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} />
      ) : (
        <div className="flex flex-col gap-3 pb-16" data-testid="mcp-links">
          <DataTableWithViews
            columns={columns}
            data={rows}
            getRowId={(r) => r.id}
            searchColumn="name"
            searchPlaceholder="Search MCP links…"
            hideViewSwitcher
            hidePaginationOnOnePage
            emptyState={<ListEmpty icon={Plug} noun="MCP links" filtered={false} description="A link gives people one address for a chosen set of this team’s tools. An admin makes one with New MCP link." />}
          />
          <p className="text-xs text-muted-foreground">Outside assistants reach test data only until production is turned on for the install.</p>
        </div>
      )}
      <NewLinkDialog open={open} onOpenChange={setOpen} />
    </PageLayout>
  );
}
