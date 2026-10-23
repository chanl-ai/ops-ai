'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { Globe, Network, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { EGRESS_COPY, EgressAddDialog } from '@/components/settings/egress-add-dialog';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField, StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { EmptyState } from '@/components/shared/empty-state';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { selectColumn } from '@/components/shared/select-column';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAddEgress, useEgress, useEgressHosts, useRemoveEgress } from '@/hooks/egress-queries';
import { useListParams } from '@/hooks/use-list-params';
import { shortDate } from '@/lib/format';
import type { EgressKind, ListedHost, ListedRange } from '@/lib/types/egress';
import { useCan } from '@/hooks/me-queries';


const added = (by: string, at: string) => (
  <div className="min-w-32">
    <div className="text-sm">{by}</div>
    <div className="text-xs text-muted-foreground">{shortDate(at)}</div>
  </div>
);

function hostColumns(canEdit: boolean, onRemove: (v: string) => void): ColumnDef<ListedHost>[] {
  return [
    // The host is the id of its row, so there is no separate Id column.
    selectColumn<ListedHost>((h) => h.host),
    { accessorKey: 'host', header: ({ column }) => <DataTableColumnHeader column={column} title="Host" />, cell: ({ row }) => <code className="font-mono text-sm">{row.original.host}</code>, enableHiding: false },
    { accessorKey: 'note', header: 'Note', cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.note || '—'}</span> },
    {
      id: 'modules',
      header: 'Called by',
      cell: ({ row }) =>
        row.original.modules.length ? (
          <div className="flex flex-wrap gap-1">
            {row.original.modules.map((m) => (
              <Badge key={m} variant="outline" className="font-mono text-[11px] font-normal" asChild>
                <Link href={`/tools/${m}`}>{m}</Link>
              </Badge>
            ))}
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">No module yet</span>
        ),
    },
    { accessorKey: 'addedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Added" />, cell: ({ row }) => added(row.original.addedBy, row.original.addedAt) },
    ...(canEdit ? [actions<ListedHost>((h) => onRemove(h.host))] : []),
  ];
}

function rangeColumns(canEdit: boolean, onRemove: (v: string) => void): ColumnDef<ListedRange>[] {
  return [
    selectColumn<ListedRange>((r) => r.cidr),
    { accessorKey: 'cidr', header: ({ column }) => <DataTableColumnHeader column={column} title="Range" />, cell: ({ row }) => <code className="font-mono text-sm">{row.original.cidr}</code>, enableHiding: false },
    { accessorKey: 'note', header: 'Note', cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.note || '—'}</span> },
    { accessorKey: 'addedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Added" />, cell: ({ row }) => added(row.original.addedBy, row.original.addedAt) },
    ...(canEdit ? [actions<ListedRange>((r) => onRemove(r.cidr))] : []),
  ];
}

function actions<T>(onRemove: (row: T) => void): ColumnDef<T> {
  return {
    id: 'actions',
    meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
    cell: ({ row }) => (
      <StopRowClick>
        <DataTableRowActions row={row} actions={[{ label: 'Remove', icon: Trash2, variant: 'destructive', onClick: (r) => onRemove(r.original) }]} />
      </StopRowClick>
    ),
    enableHiding: false,
  };
}


export default function EgressPage() {
  const query = useEgress();
  // Hosts grow with every module and page on the server; private ranges stay few and come whole with the list.
  const hostList = useListParams('host');
  const hostPage = useEgressHosts(hostList.params);
  const [hostFilterResetKey, setHostFilterResetKey] = React.useState(0);
  const remove = useRemoveEgress();
  // The allow-list decides what every tool may reach, so only the Security team's admins change it; everyone else reads it.
  const canEdit = useCan('secrets_egress', 'manage') === true;
  const [adding, setAdding] = React.useState<EgressKind | null>(null);
  const [removing, setRemoving] = React.useState<{ kind: EgressKind; value: string } | null>(null);
  const hosts = React.useMemo(() => hostColumns(canEdit, (value) => setRemoving({ kind: 'host', value })), [canEdit]);
  const ranges = React.useMemo(() => rangeColumns(canEdit, (value) => setRemoving({ kind: 'range', value })), [canEdit]);

  return (
    <SettingsPageLayout
      section="Egress"
      description="Where tool calls may go. A call reaches a listed host over https only, and an address in a private range only when that range is listed too."
      actions={
        canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setAdding('range')}>
              <Network className="size-4" /> Add range
            </Button>
            <Button onClick={() => setAdding('host')}>
              <Plus className="size-4" /> Add host
            </Button>
          </div>
        )
      }
    >
      {!canEdit && (
        <Alert>
          <AlertDescription>Only a workspace admin can change the allow-list. You can see what is listed and which modules call each host.</AlertDescription>
        </Alert>
      )}
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : query.isError && !query.data ? (
        <QueryError what="the egress allow-list" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <>
          <section className="flex flex-col gap-2" data-testid="egress-hosts">
            <h3 className="text-sm font-semibold">Hosts</h3>
            {hostPage.isPending ? (
              <PageSkeleton statCards={0} tableRows={4} />
            ) : hostPage.isError && !hostPage.data ? (
              <QueryError what="the host list" onRetry={() => hostPage.refetch()} error={hostPage.error} retrying={hostPage.isFetching} />
            ) : (
              <DataTableWithViews
                columns={hosts}
                data={hostPage.data?.data ?? []}
                getRowId={(h) => h.host}
                searchColumn="host"
                searchPlaceholder="Search hosts or notes…"
                onColumnFiltersChange={hostList.onColumnFiltersChange}
                serverPagination={{
                  enabled: true,
                  total: hostPage.data?.pagination.total ?? 0,
                  page: hostList.pagination.page,
                  pageSize: hostList.pagination.pageSize,
                  totalPages: hostPage.data?.pagination.totalPages,
                  onPaginationChange: hostList.setPagination,
                  isLoading: hostPage.isFetching && hostPage.isPlaceholderData,
                }}
                filterResetKey={hostFilterResetKey}
                hideViewSwitcher
                emptyState={<ListEmpty icon={Globe} noun="hosts" filtered={hostList.isFiltered} onClear={() => setHostFilterResetKey((k) => k + 1)} createLabel={canEdit ? 'Add host' : undefined} onCreate={() => setAdding('host')} description="Until a host is listed, no tool call or discovery leaves the bank." />}
              />
            )}
          </section>
          <section className="flex flex-col gap-2" data-testid="egress-ranges">
            <h3 className="text-sm font-semibold">Private ranges</h3>
            <DataTableWithViews
              columns={ranges}
              data={query.data?.ranges ?? []}
              getRowId={(r) => r.cidr}
              searchColumn="cidr"
              searchPlaceholder="Search ranges…"
              hideViewSwitcher
              emptyState={<EmptyState icon={Network} title="No private ranges listed" description="Listed hosts may resolve only to public addresses until a range is listed." />}
            />
          </section>
        </>
      )}

      <EgressAddDialog kind={adding} onOpenChange={(o) => !o && setAdding(null)} />
      <DeleteDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        entityType={removing ? EGRESS_COPY[removing.kind].noun : 'entry'}
        verb="Remove"
        entityName={removing?.value}
        description="Tool calls and discovery to it are refused from now on."
        confirmText="Remove"
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(removing!);
            toast.success(`Removed ${removing!.value}`);
            setRemoving(null);
          } catch (e) {
            // A host modules still call is refused (409) with their names, so the person knows what to change first.
            toast.error(`Couldn’t remove ${removing!.value}`, { description: (e as Error).message });
          }
        }}
      />
    </SettingsPageLayout>
  );
}
