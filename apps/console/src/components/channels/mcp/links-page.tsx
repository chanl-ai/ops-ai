'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { CheckCircle2, ExternalLink, Pause, Play, Plug, Plus, Trash2, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { ChannelTabs } from '@/components/channels/hub/channel-tabs';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { PageLayout } from '@/components/page-layout';
import { BuilderOnly } from '@/components/shared/builder-only';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useChannels } from '@/hooks/channel-queries';
import { useCan } from '@/hooks/me-queries';
import { useDeleteMcpLink, useMcpLinks, useSetMcpLinkPaused } from '@/hooks/mcp-link-queries';
import { useTeam } from '@/hooks/use-team';
import { plural, relativeTime } from '@/lib/format';
import type { McpLink } from '@/lib/types/mcp-links';

import { NewLinkDialog } from './new-link-dialog';

type Row = McpLink & { teamName: string; env: string; href: string; onRowClick: () => void; rowTestId: string };

const inValues = (row: { getValue: (id: string) => unknown }, id: string, value: string[]) => value.includes(String(row.getValue(id)));

/** Channels › MCP: the links of every team the person works in. Admins make, pause and delete them; every member opens
 * a link to see how to connect. */
export function McpLinksPage() {
  const router = useRouter();
  const kinds = useChannels({ page: 1, pageSize: 1, search: '' });
  const q = useMcpLinks();
  const remove = useDeleteMcpLink();
  const setPaused = useSetMcpLinkPaused();
  const { teams, teamId, switchTeam } = useTeam();
  const canEdit = useCan('deployments', 'edit') === true;
  const canDelete = useCan('deployments', 'delete') === true;
  const [open, setOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<McpLink | null>(null);
  const teamName = (id: string) => teams.find((t) => t.id === id)?.name ?? id;
  // A link's page, keys and calls are read in its own team, so opening another team's link works in that team.
  const openLink = (l: McpLink, href: string) => {
    if (l.teamId !== teamId) switchTeam(l.teamId);
    router.push(href);
  };
  const rows: Row[] = (q.data ?? []).map((l) => {
    const href = `/build/channels/mcp/${encodeURIComponent(l.id)}`;
    return { ...l, teamName: teamName(l.teamId), env: 'Test', href, onRowClick: () => openLink(l, href), rowTestId: `mcp-link-row-${l.slug}` };
  });
  const pause = (l: McpLink) =>
    setPaused.mutate(
      { id: l.id, paused: !l.paused },
      {
        onSuccess: () => toast.success(l.paused ? `Resumed ${l.name}` : `Paused ${l.name}`),
        onError: (e) => toast.error('Couldn’t change the link', { description: e.message }),
      },
    );
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
    { accessorKey: 'teamName', header: 'Team', filterFn: (row, id, value: string[]) => inValues(row, id, value) },
    {
      accessorKey: 'env',
      header: 'Environment',
      filterFn: (row, id, value: string[]) => inValues(row, id, value),
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
            {relativeTime(last.at)} · {ok ? (last.client ?? (last.signedIn ? 'signed-in assistant' : 'an assistant')) : last.outcome}
          </span>
        );
      },
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <DataTableRowActions
          row={row}
          actions={[
            { label: 'Open', icon: ExternalLink, onClick: (r) => openLink(r.original, r.original.href) },
            ...(canEdit ? [{ label: row.original.paused ? 'Resume' : 'Pause', icon: row.original.paused ? Play : Pause, onClick: () => pause(row.original) }] : []),
            ...(canDelete ? [{ label: 'Delete', icon: Trash2, variant: 'destructive' as const, onClick: () => setDeleting(row.original) }] : []),
          ]}
        />
      ),
    },
  ];
  const options = (key: 'teamName' | 'env') => [...new Set(rows.map((r) => r[key]))].map((v) => ({ label: v, value: v }));
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
            filters={[
              { column: 'teamName', title: 'Team', options: options('teamName') },
              { column: 'env', title: 'Environment', options: options('env') },
            ]}
            emptyState={<ListEmpty icon={Plug} noun="MCP links" filtered={false} description="A link gives people one address for a chosen set of this team’s tools. An admin makes one with New MCP link." />}
          />
          <p className="text-xs text-muted-foreground">Outside assistants reach test data only until production is turned on for the install.</p>
        </div>
      )}
      <NewLinkDialog open={open} onOpenChange={setOpen} />
      {deleting && (
        <ConfirmActionDialog
          open
          onOpenChange={(o) => !o && setDeleting(null)}
          title={`Delete ${deleting.name}?`}
          consequence="Its address stops answering and every key made for it stops working. Its calls stay in Activity."
          runsNow
          confirmLabel="Delete link"
          destructive
          isPending={remove.isPending}
          onConfirm={() =>
            remove
              .mutateAsync(deleting.id)
              .then(() => {
                toast.success(`Deleted ${deleting.name}`);
                setDeleting(null);
              })
              .catch((e: Error) => toast.error('Couldn’t delete the link', { description: e.message }))
          }
        />
      )}
    </PageLayout>
  );
}
