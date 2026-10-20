'use client';

import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { Code, Hash, Mail, MessagesSquare, Plug, Users, type LucideIcon } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { RecordTable } from '@/components/shared/setting/record-table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { plural } from '@/lib/format';

import { CHANNEL_TYPES, ROOT, type ChannelType, type Connection } from '../_sample/data';
import { ConnectionStatusDot } from './layout';
import { ServesPicker } from './serves-picker';

export const TYPE_ICON: Record<ChannelType, LucideIcon> = { email: Mail, chat: MessagesSquare, api: Code, mcp: Plug, slack: Hash, teams: Users };
export const TYPE_LABEL: Record<ChannelType, string> = Object.fromEntries(CHANNEL_TYPES.map((t) => [t.type, t.title])) as Record<ChannelType, string>;

/**
 * One card per kind of channel with a state read from its connections, never a bare count (Active, Needs attention,
 * Not set up, Coming soon), and exactly one action.
 */
export function ChannelGallery({ connections }: { connections: Connection[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="channel-gallery">
      {CHANNEL_TYPES.map((t) => {
        const Icon = TYPE_ICON[t.type];
        const rows = connections.filter((c) => c.type === t.type);
        const stuck = rows.filter((c) => c.status === 'attention').length;
        const live = rows.filter((c) => c.status === 'connected').length;
        return (
          <Card key={t.type} className="gap-3" data-testid={`gallery-${t.type}`}>
            <CardHeader className="flex flex-row items-center gap-3 px-4 pt-4">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted">
                <Icon className="size-4 text-muted-foreground" />
              </span>
              <CardTitle className="min-w-0 flex-1 truncate text-sm">{t.title}</CardTitle>
              {!t.built ? (
                <Badge variant="outline">Coming soon</Badge>
              ) : stuck ? (
                <Badge variant="destructive">{plural(stuck, 'needs attention', 'need attention')}</Badge>
              ) : live ? (
                <Badge variant="secondary">Active · {live}</Badge>
              ) : (
                <Badge variant="outline">Not set up</Badge>
              )}
            </CardHeader>
            <CardContent className="px-4 pb-0">
              <CardDescription className="line-clamp-2 min-h-10 text-xs">{t.description}</CardDescription>
            </CardContent>
            <CardFooter className="mt-auto justify-end border-t px-4 pb-4 [.border-t]:pt-3">
              <Button asChild size="sm" variant={t.built && !rows.length ? 'default' : 'outline'} data-testid={`gallery-action-${t.type}`}>
                <Link href={t.href}>{!t.built ? 'Preview' : rows.length ? 'Manage' : 'Connect'}</Link>
              </Button>
            </CardFooter>
          </Card>
        );
      })}
    </div>
  );
}

type ConnectionRow = Connection & { href?: string; onRowClick?: (r: Connection) => void; rowTestId: string };

const COLUMNS: ColumnDef<ConnectionRow>[] = [
  {
    accessorKey: 'name',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Connection" />,
    cell: ({ row }) => {
      const Icon = TYPE_ICON[row.original.type];
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
  { accessorKey: 'type', header: 'Channel', cell: ({ row }) => TYPE_LABEL[row.original.type] },
  { id: 'serves', header: 'Serves', cell: ({ row }) => <ServesPicker connection={row.original} /> },
  { accessorKey: 'status', header: 'Status', cell: ({ row }) => <ConnectionStatusDot status={row.original.status} at={row.original.lastActivityAt} problem={row.original.problem} /> },
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
  { accessorKey: 'team', header: 'Team' },
];

/** Every connection in the workspace. A mailbox opens its settings drawer; the others open their channel's page. */
export function AllConnections({ connections, onOpenMailbox, linkOthers = true, oneKind = false }: { connections: Connection[]; onOpenMailbox: (c: Connection) => void; linkOthers?: boolean; oneKind?: boolean }) {
  const rows: ConnectionRow[] = connections.map((c) => (c.type === 'email' ? { ...c, onRowClick: onOpenMailbox, rowTestId: `connection-${c.id}` } : { ...c, href: linkOthers ? `${ROOT}/${c.type}` : undefined, rowTestId: `connection-${c.id}` }));
  // A channel kind's own page lists one kind, so its Channel column says nothing.
  return <RecordTable columns={oneKind ? COLUMNS.filter((c) => (c as { accessorKey?: string }).accessorKey !== 'type') : COLUMNS} data={rows} nameOf={(r) => r.name} searchPlaceholder="Search connections…" />;
}
