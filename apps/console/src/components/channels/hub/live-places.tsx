'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { Activity, Route } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { QueryError } from '@/components/shared/query-states';
import { StatusDot } from '@/components/shared/setting/status-dot';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { useLivePlaces } from '@/hooks/channel-queries';
import { useActivityCount } from '@/hooks/activity-queries';
import { facetFilterFn } from '@/hooks/use-list-params';
import { plural, relativeTime } from '@/lib/format';
import type { LivePlaces } from '@/lib/types/channels';

import { HEALTH_WORD, kindInfo } from './kinds';

type Place = LivePlaces['rows'][number] & { id: string; channel: string; versionKey: string; healthWord: string; href: string; rowTestId: string };

const COLUMNS: ColumnDef<Place>[] = [
  {
    id: 'where',
    accessorFn: (r) => r.where.name,
    header: 'Where it answers',
    cell: ({ row }) => {
      const w = row.original.where;
      const Icon = w.kind === 'channel' && w.type ? kindInfo(w.type).icon : Route;
      return (
        <Link href={row.original.href} className="flex min-w-0 items-center gap-2 underline-offset-4 hover:underline">
          <Icon className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate font-medium">{w.name}</span>
        </Link>
      );
    },
    enableHiding: false,
  },
  { accessorKey: 'channel', header: 'Channel', filterFn: facetFilterFn },
  {
    id: 'version',
    accessorKey: 'versionKey',
    header: 'Version live',
    cell: ({ row }) => (
      <span className="flex flex-wrap items-center gap-1.5 whitespace-nowrap">
        <span className="font-medium tabular-nums">v{row.original.version}</span>
        <span className="text-xs text-muted-foreground">{row.original.pinned ? 'pinned' : 'latest'}</span>
        {row.original.behind > 0 && (
          <Badge variant="outline" className="border-warning/40 text-warning-text">
            {row.original.behind} behind
          </Badge>
        )}
      </span>
    ),
    filterFn: facetFilterFn,
  },
  { id: 'health', accessorKey: 'healthWord', header: 'Status', filterFn: facetFilterFn, cell: ({ row }) => <StatusDot status={row.original.health} label={row.original.health === 'ok' ? 'Connected' : HEALTH_WORD[row.original.health]} /> },
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
  { id: 'last', header: 'Last activity', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.lastActivityAt ? relativeTime(row.original.lastActivityAt) : 'None yet'}</span> },
];

/**
 * Where an agent or workflow is live: which versions answer in how many places, then every place with its version,
 * status and traffic (GET /v1/{agents|workflows}/{id}/live). A place is changed on Channels; versions are this record's.
 */
export function LivePlacesPanel({ kind, id, name, between }: { kind: 'agent' | 'workflow'; id: string; name: string; between?: React.ReactNode }) {
  const q = useLivePlaces(kind, id);
  const rows: Place[] = React.useMemo(
    () =>
      (q.data?.rows ?? []).map((r) => ({
        ...r,
        id: `${r.where.kind}:${r.where.id}`,
        channel: r.where.kind === 'workflow_step' ? 'Workflow step' : r.where.type ? kindInfo(r.where.type).title : 'Channel',
        versionKey: `v${r.version}`,
        healthWord: r.health === 'ok' ? 'Connected' : HEALTH_WORD[r.health],
        href: r.where.kind === 'workflow_step' ? `/workflows/${encodeURIComponent(r.where.workflowId ?? r.where.id)}` : r.where.type === 'email' ? `/channels/email/${encodeURIComponent(r.where.id)}` : '/channels/chat',
        rowTestId: `live-${r.where.kind}-${r.where.id}`,
      })),
    [q.data],
  );
  const sources = React.useMemo(() => [`${kind}:${id}`, ...(q.data?.rows ?? []).filter((r) => r.where.kind === 'channel').map((r) => `channel:${r.where.id}`)], [kind, id, q.data]);
  const count = useActivityCount(sources);
  if (q.isPending) return <Skeleton className="h-64 w-full" />;
  if (q.isError) return <QueryError what={`where ${name} is live`} error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />;
  const latest = q.data.latestVersion;
  return (
    <div className="flex flex-col gap-4">
      <Card className="gap-3" data-testid="versions-live">
        <CardHeader>
          <CardTitle>Versions live</CardTitle>
          <CardDescription>Published v{latest}. A place follows the latest published version or pins one; publishing never moves a pinned one.</CardDescription>
          <CardAction>
            <Button asChild variant="outline" size="sm">
              <Link href={`/activity?${new URLSearchParams([...sources.map((s) => ['source', s] as [string, string]), ['name', name]])}`}>
                <Activity className="size-4" /> View activity{count.data != null ? ` · ${count.data.toLocaleString('en-CA')}` : ''}
              </Link>
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {q.data.versions.length ? (
            <ItemGroup className="gap-2">
              {[...q.data.versions]
                .sort((a, b) => b.version - a.version)
                .map((v) => (
                  <Item key={v.version} variant="outline" size="sm" data-testid={`version-live-${v.version}`}>
                    <ItemContent>
                      <ItemTitle>
                        v{v.version} {v.version === latest ? <Badge variant="secondary">Latest</Badge> : <Badge variant="outline">{plural(latest - v.version, 'version behind', 'versions behind')}</Badge>}
                      </ItemTitle>
                      <ItemDescription>Live in {plural(v.places, 'place', 'places')}</ItemDescription>
                    </ItemContent>
                  </Item>
                ))}
            </ItemGroup>
          ) : (
            <p className="text-sm text-muted-foreground">Not live anywhere yet. Embed it on a page, or add it as a step on a workflow’s canvas.</p>
          )}
        </CardContent>
      </Card>
      {between}
      {rows.length > 0 && (
        <DataTableWithViews
          columns={COLUMNS}
          data={rows.map((r) => ({ ...r, onRowClick: undefined }))}
          getRowId={(r) => r.id}
          searchColumn="where"
          searchPlaceholder="Search where it answers…"
          hideViewSwitcher
          filters={[
            { column: 'channel', title: 'Channel', options: [...new Set(rows.map((r) => r.channel))].map((c) => ({ label: c, value: c })) },
            { column: 'version', title: 'Version', options: [...new Set(rows.map((r) => r.versionKey))].map((v) => ({ label: v, value: v })) },
            { column: 'health', title: 'Status', options: [...new Set(rows.map((r) => r.healthWord))].map((v) => ({ label: v, value: v })) },
          ]}
        />
      )}
    </div>
  );
}
