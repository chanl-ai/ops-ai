'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, Plus, ShieldOff } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ApiKeyDialog } from '@/components/settings/api-key-dialog';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useApiKeys, useCreateApiKey, useRevokeApiKey, useSettingsLookups } from '@/hooks/settings-queries';
import { useListParams } from '@/hooks/use-list-params';
import { useTeam } from '@/hooks/use-team';
import { relativeTime, shortDate } from '@/lib/format';
import type { ApiKey } from '@/lib/types/settings';

function columns(showTeam: boolean, onRevoke: (k: ApiKey) => void): ColumnDef<ApiKey>[] {
  return [
    {
      id: 'name',
      accessorFn: (k) => `${k.name} ${k.prefix} ${k.createdBy}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Key" />,
      cell: ({ row }) => (
        <div className="min-w-52">
          <div className="font-medium">{row.original.name}</div>
          <code className="font-mono text-[11px] text-muted-foreground">{row.original.prefix}…</code>
        </div>
      ),
      enableHiding: false,
    },
    ...(showTeam ? [{ accessorKey: 'team', header: ({ column }) => <DataTableColumnHeader column={column} title="Team" />, cell: ({ row }) => <span className="whitespace-nowrap">{row.original.team}</span> } as ColumnDef<ApiKey>] : []),
    {
      accessorKey: 'scopes',
      header: 'Scopes',
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-1">
          {row.original.scopes.map((s) => (
            <Badge key={s} variant="outline" className="font-mono text-[11px] font-normal">
              {s}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      accessorKey: 'createdBy',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Created" />,
      cell: ({ row }) => (
        <div className="min-w-32">
          <div className="text-sm">{row.original.createdBy}</div>
          <div className="text-xs text-muted-foreground">{shortDate(row.original.createdAt)}</div>
        </div>
      ),
    },
    { accessorKey: 'lastUsedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last used" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.lastUsedAt ? relativeTime(row.original.lastUsedAt) : 'Never'}</span> },
    {
      accessorKey: 'expiresAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Expires" />,
      cell: ({ row }) => {
        const at = row.original.expiresAt;
        if (!at) return <span className="text-xs text-muted-foreground">Never</span>;
        const days = Math.round((new Date(at).getTime() - Date.now()) / 86_400_000);
        return <span className={days <= 30 ? 'text-xs font-medium whitespace-nowrap text-amber-700 dark:text-amber-400' : 'text-xs whitespace-nowrap text-muted-foreground'}>{days <= 30 ? `In ${days} days` : shortDate(at)}</span>;
      },
    },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions row={row} actions={[{ label: 'Revoke', icon: ShieldOff, variant: 'destructive', onClick: (r) => onRevoke(r.original) }]} />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

export default function ApiKeysPage() {
  const { team, teams } = useTeam();
  const showTeam = team?.scope === 'all';
  const list = useListParams('name');
  const query = useApiKeys(list.params);
  const lookups = useSettingsLookups();
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();
  const [createOpen, setCreateOpen] = React.useState(false);
  const [revoking, setRevoking] = React.useState<ApiKey | null>(null);
  const cols = React.useMemo(() => columns(showTeam, setRevoking), [showTeam]);

  return (
    <SettingsPageLayout
      section="API keys"
      description="Keys for systems that start runs or read logs. A key is shown once, when it is created."
      actions={
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" /> Create key
        </Button>
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={5} />
      ) : query.isError && !query.data ? (
        <QueryError what="API keys" onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={query.data?.data ?? []}
          getRowId={(k) => k.id}
          searchColumn="name"
          searchPlaceholder="Search names, prefixes or creators…"
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
          emptyState={<ListEmpty icon={KeyRound} noun="API keys" filtered={list.isFiltered} createLabel="Create key" onCreate={() => setCreateOpen(true)} description="Create a key for each system that calls Ops AI, so each one can be revoked on its own." />}
        />
      )}

      <ApiKeyDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        scopes={lookups.data?.apiScopes ?? []}
        teams={team?.scope === 'all' ? teams.map((t) => ({ id: t.id, name: t.name })) : undefined}
        defaultTeamId={team?.id}
        isPending={create.isPending}
        onSubmit={(input) => create.mutateAsync(input)}
      />
      <DeleteDialog
        open={!!revoking}
        onOpenChange={(o) => !o && setRevoking(null)}
        entityType="API key"
        verb="Revoke"
        entityName={revoking?.name}
        description={`Calls using ${revoking?.prefix ?? 'this key'}… get 401 from now on. The calling system needs a new key to keep working.`}
        confirmText="Revoke key"
        isLoading={revoke.isPending}
        onConfirm={async () => {
          try {
            await revoke.mutateAsync(revoking!.id);
            toast.success(`Revoked ${revoking!.name}`);
            setRevoking(null);
          } catch (e) {
            toast.error('Couldn’t revoke the key', { description: (e as Error).message });
          }
        }}
      />
    </SettingsPageLayout>
  );
}
