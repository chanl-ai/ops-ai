'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import Link from 'next/link';
import { HardDrive, KeySquare, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { CREDENTIAL_KIND_LABEL } from '@/components/files/file-meta';
import { SecretDialog, USED_BY_SHOWN } from '@/components/settings/secret-dialog';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { selectColumn } from '@/components/shared/select-column';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { Row, Rows, Section } from '@/components/shared/surface';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useStorageCredentials } from '@/hooks/file-queries';
import { useDeleteSecret, useSecretsPage } from '@/hooks/secrets-queries';
import { useTeam } from '@/hooks/use-team';
import { useListParams } from '@/hooks/use-list-params';
import { relativeTime, shortDate } from '@/lib/format';
import type { SecretMeta } from '@/lib/types/secrets';
import { useCan } from '@/hooks/me-queries';

function columns(canEdit: boolean, onRotate: (s: SecretMeta) => void, onDelete: (s: SecretMeta) => void): ColumnDef<SecretMeta>[] {
  const cols: ColumnDef<SecretMeta>[] = [
    // The name is the secret's id, so there is no separate Id column.
    selectColumn<SecretMeta>((s) => s.name),
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Name" />,
      cell: ({ row }) => (
        <div className="min-w-48">
          <code className="font-mono text-sm">{row.original.name}</code>
          <div className="font-mono text-[11px] text-muted-foreground">{`{{${row.original.name}}}`} in a header</div>
        </div>
      ),
      enableHiding: false,
    },
    {
      id: 'usedBy',
      accessorFn: (s) => s.usedBy.length,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Used by" />,
      cell: ({ row }) =>
        row.original.usedBy.length ? (
          <StopRowClick align="start">
            <div className="flex min-w-48 flex-wrap gap-1" data-testid={`secret-users-${row.original.name}`}>
              {row.original.usedBy.slice(0, USED_BY_SHOWN).map((u) => (
                <Badge key={`${u.moduleId}:${u.operation}`} variant="outline" asChild className="font-mono font-normal">
                  <Link href={`/tools/${u.moduleId}/operations/${encodeURIComponent(u.operation)}`} title={`${u.moduleName}${u.staged ? ', staged edit' : ''}`}>
                    {u.operation}
                    {u.staged && <span className="font-sans text-warning-text">staged</span>}
                  </Link>
                </Badge>
              ))}
              {row.original.usedBy.length > USED_BY_SHOWN && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button type="button" className="rounded-sm text-xs text-muted-foreground underline-offset-4 hover:underline" data-testid={`secret-users-more-${row.original.name}`}>
                      and {row.original.usedBy.length - USED_BY_SHOWN} more
                    </button>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs break-words font-mono">{row.original.usedBy.slice(USED_BY_SHOWN).map((u) => u.operation).join(', ')}</TooltipContent>
                </Tooltip>
              )}
            </div>
          </StopRowClick>
        ) : (
          <span className="text-sm text-muted-foreground">No operation</span>
        ),
    },
    { accessorKey: 'version', header: ({ column }) => <DataTableColumnHeader column={column} title="Version" />, cell: ({ row }) => <span className="text-sm tabular-nums">v{row.original.version}</span> },
    {
      accessorKey: 'createdAt',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Created" />,
      cell: ({ row }) => (
        <div className="min-w-32">
          <div className="text-sm">{row.original.createdBy}</div>
          <div className="text-xs text-muted-foreground">{shortDate(row.original.createdAt)}</div>
        </div>
      ),
    },
    { accessorKey: 'rotatedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Rotated" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.rotatedAt ? relativeTime(row.original.rotatedAt) : 'Never'}</span> },
    { accessorKey: 'lastUsedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last used" />, cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.lastUsedAt ? relativeTime(row.original.lastUsedAt) : 'Never'}</span> },
    {
      id: 'actions',
      meta: { className: 'sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]' },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              { label: 'Rotate', icon: RefreshCw, onClick: (r) => onRotate(r.original) },
              {
                label: 'Delete',
                icon: Trash2,
                variant: 'destructive',
                onClick: (r) => onDelete(r.original),
                // tools-service refuses it too (409); saying why here saves the round trip.
                disabledReason: row.original.usedBy.length ? `Read by ${row.original.usedBy.length} ${row.original.usedBy.length === 1 ? 'operation' : 'operations'}` : undefined,
              },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
  // Rotating or deleting is the Security team's admins' to do; everyone else reads the names.
  return canEdit ? cols : cols.filter((c) => c.id !== 'actions');
}

export default function SecretsPage() {
  const list = useListParams('name');
  const [filterResetKey, setFilterResetKey] = React.useState(0);
  const query = useSecretsPage(list.params);
  const remove = useDeleteSecret();
  const [dialog, setDialog] = React.useState<{ rotating: SecretMeta | null } | null>(null);
  const [deleting, setDeleting] = React.useState<SecretMeta | null>(null);
  const { team } = useTeam();
  // A secret is a credential every tool call may send, so only the Security team's admins add, rotate or delete one.
  const canEdit = useCan('secrets_egress', 'create') === true;
  const cols = React.useMemo(() => columns(canEdit, (s) => setDialog({ rotating: s }), setDeleting), [canEdit]);

  return (
    <SettingsPageLayout
      section="Secrets"
      description={`Credentials ${team ? `${team.name}'s` : 'this team’s'} tool calls send, such as API keys. A value is encrypted, never shown again, and scrubbed from whatever a system answers.`}
      actions={
        canEdit ? (
          <Button onClick={() => setDialog({ rotating: null })}>
            <Plus className="size-4" /> Add secret
          </Button>
        ) : undefined
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : query.isError && !query.data ? (
        <QueryError what="secrets" onRetry={() => query.refetch()} error={query.error} retrying={query.isFetching} />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={query.data?.data ?? []}
          getRowId={(s) => s.name}
          searchColumn="name"
          searchPlaceholder="Search secrets…"
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
          filterResetKey={filterResetKey}
          hideViewSwitcher
          // The page header already carries Add secret; a second one in the empty state doubles it.
          emptyState={<ListEmpty icon={KeySquare} noun="secrets" filtered={list.isFiltered} onClear={() => setFilterResetKey((k) => k + 1)} description="Add the credential a tool module's header names, such as {{STATEMENTS_KEY}}." />}
        />
      )}

      {canEdit && <StorageCredentials />}

      <SecretDialog open={!!dialog} rotating={dialog?.rotating ?? null} onOpenChange={(o) => !o && setDialog(null)} />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="secret"
        entityName={deleting?.name}
        description="Calls whose headers name it are refused with SECRET_MISSING from now on, and nothing is sent."
        confirmText="Delete secret"
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync(deleting!.name);
            toast.success(`Deleted ${deleting!.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error(`Couldn’t delete ${deleting!.name}`, { description: (e as Error).message });
          }
        }}
      />
    </SettingsPageLayout>
  );
}

/** The storage credentials files-service keeps (c-100), listed here so every credential is in one place. Each stays in
 * the service that uses it; they are added and changed on the Storage page, where each target names its credential. */
function StorageCredentials() {
  const creds = useStorageCredentials();
  return (
    <Section
      title="Storage credentials"
      description="Kept by files-service for the storage it writes to. Values are never shown."
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/settings/workspace/storage">
            <HardDrive className="size-4" /> Storage settings
          </Link>
        </Button>
      }
      flush
    >
      {creds.isPending ? (
        <div className="flex flex-col gap-2 p-4" data-testid="storage-credentials-loading">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : creds.isError ? (
        <div className="p-4">
          <QueryError what="storage credentials" onRetry={() => creds.refetch()} error={creds.error} retrying={creds.isFetching} />
        </div>
      ) : !creds.data?.length ? (
        <p className="p-4 text-sm text-muted-foreground">No storage credentials. Uploads use the storage the platform was set up with.</p>
      ) : (
        <Rows testId="storage-credentials">
          {creds.data.map((c) => (
            <Row
              key={c.name}
              leading={<HardDrive className="size-4 text-muted-foreground" />}
              title={<code className="font-mono text-sm">{c.name}</code>}
              description={`${CREDENTIAL_KIND_LABEL[c.kind]} · set by ${c.setBy} ${relativeTime(c.setAt)}`}
            />
          ))}
        </Rows>
      )}
    </Section>
  );
}
