'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { Radio } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { idColumn } from '@/components/shared/id-column';
import { ListEmpty } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { StatusDot } from '@/components/shared/setting/status-dot';
import { plural } from '@/lib/format';
import type { ChannelRow, ChannelType } from '@/lib/types/channels';
import type { PaginationMeta } from '@/lib/types/pagination';
import type { PaginationState } from '@/lib/types/pagination';

import { HEALTH_WORD, kindInfo } from './kinds';
import { ServesCell } from './serves-cell';

/** Where a channel's own settings live: a mailbox's page, the agent's Channels tab for an embed, API keys for a key. */
export function channelHref(c: ChannelRow): string {
  if (c.type === 'email') return `/channels/email/${encodeURIComponent(c.id)}`;
  if (c.type === 'chat' && c.serves) return `/agents/${encodeURIComponent(c.serves.id)}?tab=channels`;
  return '/settings/api-keys';
}

type Row = ChannelRow & { href: string; onRowClick: () => void; rowTestId: string };

const columns = (oneKind: boolean): ColumnDef<Row>[] => [
  selectColumn<Row>((r) => r.name),
  idColumn<Row>((r) => r.id),
  {
    accessorKey: 'name',
    header: 'Connection',
    cell: ({ row }) => {
      const Icon = kindInfo(row.original.type).icon;
      return (
        <span className="flex min-w-0 items-center gap-2">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0">
            <span className="block truncate font-medium">{row.original.name}</span>
            <span className="block truncate text-xs text-muted-foreground">{row.original.detail}</span>
          </span>
        </span>
      );
    },
    enableHiding: false,
  },
  ...(oneKind ? [] : [{ accessorKey: 'type', header: 'Channel', cell: ({ row }: { row: { original: Row } }) => kindInfo(row.original.type).title } as ColumnDef<Row>]),
  { id: 'serves', header: 'Serves', cell: ({ row }) => <ServesCell channel={row.original} /> },
  {
    id: 'health',
    header: 'Status',
    cell: ({ row }) => {
      const c = row.original;
      if (c.paused) return <StatusDot status="idle" label="Paused" at={c.health.checkedAt ?? undefined} />;
      return <StatusDot status={c.health.state} label={c.health.state === 'ok' ? 'Connected' : HEALTH_WORD[c.health.state]} at={c.health.checkedAt ?? undefined} detail={c.health.reason ?? undefined} />;
    },
  },
  {
    id: 'traffic',
    header: 'Traffic · 24h',
    cell: ({ row }) =>
      row.original.traffic24h === null ? (
        <span className="text-muted-foreground">—</span>
      ) : (
        <span className="whitespace-nowrap tabular-nums">
          {row.original.traffic24h.toLocaleString('en-CA')}
          {(row.original.errors24h ?? 0) > 0 && <span className="ml-1.5 text-destructive">{plural(row.original.errors24h ?? 0, 'error', 'errors')}</span>}
        </span>
      ),
  },
  { accessorKey: 'teamName', header: 'Team' },
];

/** The connections list: the shared data table, paged and searched on the server; a row opens where it is set up. */
export function ChannelTable({ rows, oneKind, kind, pagination, page, onPaginationChange, onColumnFiltersChange, loading }: { rows: ChannelRow[]; oneKind?: ChannelType; kind?: string; pagination?: PaginationMeta; page: PaginationState; onPaginationChange: (p: PaginationState) => void; onColumnFiltersChange: Parameters<typeof DataTableWithViews>[0]['onColumnFiltersChange']; loading: boolean }) {
  const router = useRouter();
  const data: Row[] = React.useMemo(() => rows.map((c) => ({ ...c, href: channelHref(c), onRowClick: () => router.push(channelHref(c)), rowTestId: `channel-row-${c.id}` })), [rows, router]);
  const cols = React.useMemo(() => columns(!!oneKind), [oneKind]);
  return (
    <DataTableWithViews
      columns={cols}
      data={data}
      getRowId={(r) => r.id}
      searchColumn="name"
      searchPlaceholder="Search connections…"
      hideViewSwitcher
      onColumnFiltersChange={onColumnFiltersChange}
      serverPagination={{ enabled: true, total: pagination?.total ?? 0, page: page.page, pageSize: page.pageSize, totalPages: pagination?.totalPages, onPaginationChange, isLoading: loading }}
      emptyState={<ListEmpty icon={Radio} noun={kind ? `${kind} connections` : 'connections'} filtered={false} description="A connection appears here once it is set up." />}
    />
  );
}
