'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { Activity, CalendarClock, Route } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { Section } from '@/components/shared/surface';
import { StatusDot } from '@/components/shared/setting/status-dot';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { Skeleton } from '@/components/ui/skeleton';
import { ScheduleAgentDialog } from './schedule-agent-dialog';
import { useLivePlaces } from '@/hooks/channel-queries';
import { useActivityCount } from '@/hooks/activity-queries';
import { useCan } from '@/hooks/me-queries';
import { facetFilterFn } from '@/hooks/use-list-params';
import { dateTime, plural, relativeTime } from '@/lib/format';
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
        <div className="flex min-w-0 flex-col">
          <Link href={row.original.href} className="flex min-w-0 items-center gap-2 underline-offset-4 hover:underline">
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate font-medium">{w.name}</span>
          </Link>
          {row.original.schedule && (
            <span className="truncate text-xs text-muted-foreground" data-testid="live-schedule">
              {row.original.schedule.words}
              {row.original.schedule.nextRun ? ` · next ${dateTime(row.original.schedule.nextRun)}` : ''}
            </span>
          )}
        </div>
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
          {(row.original.errors24h ?? 0) > 0 && <span className="ml-1.5 text-destructive-text">{plural(row.original.errors24h ?? 0, 'error', 'errors')}</span>}
        </span>
      ),
  },
  { id: 'last', header: 'Last activity', cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.lastActivityAt ? relativeTime(row.original.lastActivityAt) : 'None yet'}</span> },
];

/**
 * Where an agent or workflow is live: which versions answer in how many places, then every place with its version,
 * status and traffic (GET /v1/{agents|workflows}/{id}/live). A place is changed on Channels; versions are this record's.
 */
/** Rows in the place of the card and the table while the list loads. */
function LiveSkeleton() {
  return (
    <div className="flex flex-col gap-2" data-testid="live-skeleton">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-14 w-full" />
      ))}
    </div>
  );
}

export function LivePlacesPanel({ kind, id, name, between }: { kind: 'agent' | 'workflow'; id: string; name: string; between?: React.ReactNode }) {
  const q = useLivePlaces(kind, id);
  // Scheduling an agent makes a workflow and saves its schedule, so it needs all three rights.
  const mayCreate = useCan('workflows', 'create') === true;
  const mayEdit = useCan('workflows', 'edit') === true;
  const mayDeploy = useCan('deployments', 'create') === true;
  const [scheduling, setScheduling] = React.useState(false);
  const rows: Place[] = React.useMemo(
    () =>
      (q.data?.rows ?? []).map((r) => ({
        ...r,
        id: `${r.where.kind}:${r.where.id}`,
        channel: r.where.kind === 'workflow_step' ? 'Workflow step' : r.where.type ? kindInfo(r.where.type).title : 'Channel',
        versionKey: `v${r.version}`,
        healthWord: r.health === 'ok' ? 'Connected' : HEALTH_WORD[r.health],
        href: r.where.kind === 'workflow_step' ? `/build/workflows/${encodeURIComponent(r.where.workflowId ?? r.where.id)}` : r.where.type === 'email' ? `/build/channels/email/${encodeURIComponent(r.where.id)}` : '/build/channels/chat',
        rowTestId: `live-${r.where.kind}-${r.where.id}`,
      })),
    [q.data],
  );
  const sources = React.useMemo(() => [`${kind}:${id}`, ...(q.data?.rows ?? []).filter((r) => r.where.kind === 'channel').map((r) => `channel:${r.where.id}`)], [kind, id, q.data]);
  // Activity is read under activity.view; without it there is no list to link to, so nothing is asked.
  const readsActivity = useCan('activity', 'view') === true;
  const count = useActivityCount(sources, readsActivity);
  if (q.isPending) return <LiveSkeleton />;
  if (q.isError) return <QueryError what={`where this ${kind} is live`} error={q.error} onRetry={() => q.refetch()} retrying={q.isFetching} />;
  const latest = q.data.latestVersion;
  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Versions live"
        description={`Published v${latest}. A place follows the latest published version or pins one; publishing never moves a pinned one.`}
        actions={
          (readsActivity || (kind === 'agent' && mayCreate && mayEdit && mayDeploy)) && (
            <div className="flex flex-wrap gap-2">
              {kind === 'agent' && mayCreate && mayEdit && mayDeploy && (
                <Button variant="outline" size="sm" onClick={() => setScheduling(true)} aria-label="Run on a schedule" data-testid="run-on-schedule">
                  <CalendarClock className="size-4" /> Schedule
                </Button>
              )}
              {readsActivity && (
                <Button asChild variant="outline" size="sm">
                  <Link href={`/govern/activity?${new URLSearchParams([...sources.map((s) => ['source', s] as [string, string]), ['name', name]])}`}>
                    <Activity className="size-4" /> View activity{count.data != null ? ` · ${count.data.toLocaleString('en-CA')}` : ''}
                  </Link>
                </Button>
              )}
            </div>
          )
        }
        className="gap-0"
      >
        <div data-testid="versions-live">
          {q.data.versions.length ? (
            <ItemGroup className="gap-2">
              {[...q.data.versions]
                .sort((a, b) => b.version - a.version)
                .map((v) => (
                  <Item key={v.version} role="listitem" variant="outline" size="sm" data-testid={`version-live-${v.version}`}>
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
            <EmptyState icon={Route} title="Not live anywhere yet" description={`Put the ${kind} on a channel, in a workflow, or on a schedule.`} testId="live-empty" />
          )}
        </div>
      </Section>
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
      {kind === 'agent' && <ScheduleAgentDialog open={scheduling} onOpenChange={setScheduling} agentId={id} agentName={name} />}
    </div>
  );
}
