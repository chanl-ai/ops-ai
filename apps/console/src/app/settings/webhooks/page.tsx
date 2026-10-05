'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pause, Play, Plus, Trash2, Webhook as WebhookIcon } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { WebhookDeliveriesSheet } from '@/components/settings/webhook-deliveries-sheet';
import { WebhookDialog } from '@/components/settings/webhook-dialog';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useCreateWebhook, useDeleteWebhook, useSetWebhookStatus, useResendDelivery, useSettingsLookups, useWebhookDeliveries, useWebhooks } from '@/hooks/settings-queries';
import { useListParams } from '@/hooks/use-list-params';
import { useTeam } from '@/hooks/use-team';
import { count, pct, relativeTime } from '@/lib/format';
import type { Webhook } from '@/lib/types/settings';
import { cn } from '@/lib/utils';

type Row = Webhook & { onRowClick: (w: Webhook) => void };

const STATUS_TONE: Record<Webhook['status'], string> = {
  active: 'text-emerald-700 dark:text-emerald-400',
  paused: 'text-muted-foreground',
  failing: 'text-red-600 dark:text-red-400',
};

function columns(showTeam: boolean): ColumnDef<Row>[] {
  return [
    {
      id: 'name',
      accessorFn: (w) => `${w.name} ${w.url} ${w.events.join(' ')}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Webhook" />,
      cell: ({ row }) => (
        <div className="max-w-72 min-w-48">
          <div className="truncate font-medium" title={row.original.name}>
            {row.original.name}
          </div>
          <div className="truncate font-mono text-[11px] text-muted-foreground" title={row.original.url}>
            {row.original.url}
          </div>
        </div>
      ),
      enableHiding: false,
    },
    ...(showTeam ? [{ accessorKey: 'team', header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.team}</span> } as ColumnDef<Row>] : []),
    { accessorKey: 'events', header: 'Events', cell: ({ row }) => <span className="text-sm whitespace-nowrap">{row.original.events.length === 1 ? row.original.events[0] : `${row.original.events.length} events`}</span> },
    { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <span className={cn('text-xs font-medium capitalize', STATUS_TONE[row.original.status])}>{row.original.status}</span> },
    {
      accessorKey: 'successRate7d',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Delivered · 7 days" />,
      cell: ({ row }) => {
        const { successRate7d: rate, deliveries7d: n } = row.original;
        if (rate == null) return <span className="text-sm whitespace-nowrap text-muted-foreground">No deliveries</span>;
        return (
          <span className={cn('whitespace-nowrap tabular-nums', rate < 0.95 && 'font-medium text-red-600 dark:text-red-400')}>
            {pct(rate)} <span className="text-xs text-muted-foreground">of {count(n)}</span>
          </span>
        );
      },
    },
    { accessorKey: 'lastDeliveryAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last delivery" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{relativeTime(row.original.lastDeliveryAt)}</span> },
  ];
}

export default function WebhooksPage() {
  const { team } = useTeam();
  const showTeam = team?.scope === 'all';
  const list = useListParams('name');
  const query = useWebhooks(list.params);
  const lookups = useSettingsLookups();
  const create = useCreateWebhook();
  const setStatus = useSetWebhookStatus();
  const remove = useDeleteWebhook();
  const resend = useResendDelivery();
  const [addOpen, setAddOpen] = React.useState(false);
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState<Webhook | null>(null);
  const [status, setDeliveryStatus] = React.useState('all');
  const [page, setPage] = React.useState(1);
  const deliveries = useWebhookDeliveries(activeId, { page, pageSize: 10, filters: status === 'all' ? {} : { status: [status] } });

  const hooks = query.data?.data ?? [];
  const index = hooks.findIndex((w) => w.id === activeId);
  const active = index >= 0 ? hooks[index] : null;
  const open = (wid: string | null) => {
    setActiveId(wid);
    setPage(1);
    setDeliveryStatus('all');
  };
  const rows: Row[] = React.useMemo(() => hooks.map((w) => ({ ...w, onRowClick: (x: Webhook) => open(x.id) })), [hooks]);
  const cols = React.useMemo(() => columns(showTeam), [showTeam]);

  return (
    <SettingsPageLayout
      section="Webhooks"
      description="Send events to the bank’s other systems as they happen. Open one to see its deliveries."
      actions={
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="size-4" /> Add webhook
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={5} />
      ) : query.isError && !query.data ? (
        <QueryError what="webhooks" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={rows}
          getRowId={(w) => w.id}
          searchColumn="name"
          searchPlaceholder="Search names, URLs or events…"
          initialColumnVisibility={{ events: false }}
          onColumnFiltersChange={list.onColumnFiltersChange}
          serverPagination={{
            enabled: true,
            total: query.data?.pagination.total ?? 0,
            page: list.pagination.page,
            pageSize: list.pagination.pageSize,
            totalPages: query.data?.pagination.totalPages,
            onPaginationChange: list.setPagination,
            isLoading: query.isFetching && query.isPlaceholderData,
          }}
          emptyState={<ListEmpty icon={WebhookIcon} noun="webhooks" filtered={list.isFiltered} createLabel="Add webhook" onCreate={() => setAddOpen(true)} description="Send review decisions, failed runs or audit entries to a SIEM, case manager or ticketing system." />}
        />
      )}

      <WebhookDeliveriesSheet
        webhook={active}
        result={deliveries.data}
        isPending={deliveries.isPending}
        isError={deliveries.isError}
        onRetry={() => deliveries.refetch()}
        onResend={
          active && active.status !== 'paused'
            ? (d) =>
                resend.mutate(
                  { id: active.id, deliveryId: d.id },
                  {
                    onSuccess: (n) => (n.status === 'success' ? toast.success(`Resent ${d.event}`) : toast.error(`Resent ${d.event}, but it failed again`, { description: n.error })),
                    onError: (e) => toast.error('Couldn’t resend', { description: e.message }),
                  },
                )
            : undefined
        }
        resendingId={resend.isPending ? resend.variables?.deliveryId : undefined}
        status={status}
        onStatusChange={(s) => {
          setDeliveryStatus(s);
          setPage(1);
        }}
        page={page}
        onPageChange={setPage}
        onOpenChange={(o) => !o && setActiveId(null)}
        navigation={
          active
            ? {
                currentIndex: index,
                totalCount: hooks.length,
                onPrev: index > 0 ? () => open(hooks[index - 1].id) : undefined,
                onNext: index < hooks.length - 1 ? () => open(hooks[index + 1].id) : undefined,
              }
            : undefined
        }
        footerActions={
          active && (
            <>
              <LoadingButton
                size="sm"
                variant="outline"
                isLoading={setStatus.isPending}
                onClick={() =>
                  setStatus.mutate(
                    { id: active.id, status: active.status === 'paused' ? 'active' : 'paused' },
                    {
                      onSuccess: (w) => toast.success(w.status === 'paused' ? `Paused ${w.name}. Events are skipped until you resume.` : `Resumed ${w.name}`),
                      onError: (e) => toast.error('Couldn’t change the webhook', { description: e.message }),
                    },
                  )
                }
              >
                {active.status === 'paused' ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
                {active.status === 'paused' ? 'Resume' : 'Pause'}
              </LoadingButton>
              <Button size="sm" variant="ghost" className="text-destructive" onClick={() => setDeleting(active)}>
                <Trash2 className="size-3.5" /> Delete
              </Button>
              <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
                Signing secret
                <Badge variant="outline" className="font-mono text-[11px] font-normal">
                  {active.secretPrefix}…
                </Badge>
              </span>
            </>
          )
        }
      />

      <WebhookDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        events={lookups.data?.webhookEvents ?? []}
        isPending={create.isPending}
        onSubmit={async (input) => {
          const w = await create.mutateAsync(input);
          toast.success(`Added ${w.name}`, { description: `Signing secret starts ${w.secretPrefix}. Verify the signature on every request.` });
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="webhook"
        entityName={deleting?.name}
        description="Events stop being sent at once and its delivery history is deleted. The receiving system is not told."
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(deleting!.id);
            toast.success(`Deleted ${deleting!.name}`);
            if (activeId === deleting!.id) setActiveId(null);
            setDeleting(null);
          } catch (e) {
            toast.error('Couldn’t delete the webhook', { description: (e as Error).message });
          }
        }}
      />
    </SettingsPageLayout>
  );
}
