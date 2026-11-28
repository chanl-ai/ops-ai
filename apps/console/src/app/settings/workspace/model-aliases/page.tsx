'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Info, Pencil, Plus, Tag } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { AliasDialog } from '@/components/models/alias-dialog';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { StopRowClick } from '@/components/shared/form-field';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { serverPagination } from '@/components/shared/server-pagination';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useCan } from '@/hooks/me-queries';
import { useModelAliasList } from '@/hooks/model-queries';
import { useProviderConnections } from '@/hooks/provider-connection-queries';
import { useListParams } from '@/hooks/use-list-params';
import { useIsMobile } from '@/hooks/use-mobile';
import { modelSetupOnly, usedByLabel } from '@/lib/model-forms';
import type { ModelAliasRow } from '@/lib/types/models';

const SORT = { name: 'name' };

function columns(onEdit: ((a: ModelAliasRow) => void) | null): ColumnDef<ModelAliasRow>[] {
  return [
    {
      accessorKey: 'name',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Alias" />,
      cell: ({ row }) => (
        <div className="min-w-0">
          <code className="font-mono text-sm">{row.original.name}</code>
          <div className="text-xs text-muted-foreground">Version {row.original.version}</div>
        </div>
      ),
      meta: { kind: 'name' },
      enableHiding: false,
    },
    {
      id: 'goesTo',
      header: 'Goes to',
      meta: { kind: 'description' },
      cell: ({ row }) => (
        <div className="min-w-0 text-sm">
          {row.original.providerName ?? 'Unknown connection'}
          <div className="text-xs text-muted-foreground">
            <code className="font-mono">{row.original.modelId}</code>
          </div>
        </div>
      ),
    },
    {
      accessorKey: 'clearedSensitivity',
      header: 'Cleared for',
      meta: { kind: 'status' },
      cell: ({ row }) => <Badge variant="secondary">{row.original.clearedSensitivity.charAt(0).toUpperCase() + row.original.clearedSensitivity.slice(1)}</Badge>,
    },
    {
      id: 'usedBy',
      header: 'Used by',
      meta: { kind: 'status' },
      cell: ({ row }) => <span className="text-sm whitespace-nowrap" data-testid="alias-used-by">{usedByLabel(row.original.usedBy)}</span>,
    },
    {
      id: 'price',
      header: 'Price per 1M tokens',
      meta: { kind: 'money' },
      cell: ({ row }) => <span className="text-xs whitespace-nowrap">{`$${row.original.inputPerMillion} / $${row.original.outputPerMillion}`}</span>,
    },
    {
      id: 'actions',
      meta: { kind: 'actions' },
      cell: ({ row }) =>
        onEdit ? (
          <StopRowClick>
            <DataTableRowActions row={row} actions={[{ label: 'Edit', icon: Pencil, onClick: (r) => onEdit(r.original) }]} />
          </StopRowClick>
        ) : null,
      enableHiding: false,
    },
  ];
}

/**
 * The account's model aliases (models-service `/v1/models/aliases`): the names builders pick on the agent page, each
 * calling a model on a connection. Repointing one saves a new version. Whoever holds settings.manage, from the roles
 * matrix, reads and changes them; anyone else is told who does.
 */
export default function ModelAliasesPage() {
  const admin = useCan('settings', 'manage') === true;
  const list = useListParams('name', undefined, undefined, SORT);
  const aliases = useModelAliasList(list.params, admin);
  // Whether any connection exists at all: an alias points at one, so without one the page says to connect first.
  const connections = useProviderConnections({ page: 1, pageSize: 1 }, admin);
  const [dialog, setDialog] = React.useState<{ editing: ModelAliasRow | null } | null>(null);
  const cols = React.useMemo(() => columns(admin ? (a) => setDialog({ editing: a }) : null), [admin]);
  const noConnections = connections.data?.pagination.total === 0;
  // On a phone the usage and price wait under View (both are on the edit dialog), so Cleared for shows in full.
  const mobile = useIsMobile();

  return (
    <SettingsPageLayout
      sample={false}
      section="Aliases"
      description="The names builders pick on the agent page, and the connection and model each one calls."
      actions={
        admin &&
        !noConnections && (
          <Button onClick={() => setDialog({ editing: null })} data-testid="alias-add">
            <Plus className="size-4" /> Make alias
          </Button>
        )
      }
    >
      {!admin ? (
        <Alert>
          <Info />
          <AlertDescription>{modelSetupOnly('model aliases')}</AlertDescription>
        </Alert>
      ) : aliases.isPending || connections.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : noConnections ? (
        <EmptyState
          icon={Tag}
          title="Connect a provider first"
          description="An alias points at a model on a connection. This workspace has none yet."
          action={{ label: 'Go to Connections', href: '/settings/workspace/model-providers' }}
        />
      ) : aliases.isError && !aliases.data ? (
        <QueryError what="model aliases" onRetry={() => aliases.refetch()} retrying={aliases.isFetching} error={aliases.error} testId="model-aliases-error" />
      ) : (
        <>
          <DataTableWithViews
            columns={cols}
            data={aliases.data?.data ?? []}
            getRowId={(a) => a.name}
            searchColumn="name"
            searchPlaceholder="Search aliases…"
            onColumnFiltersChange={list.onColumnFiltersChange}
            serverPagination={serverPagination(list, aliases)}
            serverSorting={list.serverSort}
            hideViewSwitcher
            initialColumnVisibility={mobile ? { usedBy: false, price: false } : undefined}
            emptyState={
              <ListEmpty
                icon={Tag}
                noun="aliases"
                filtered={list.isFiltered}
                createLabel="Make alias"
                onCreate={() => setDialog({ editing: null })}
                description="Builders pick an alias on the agent page, never a raw model. Make one for each model you want them to use."
              />
            }
          />
        </>
      )}
      <AliasDialog open={!!dialog} onOpenChange={(o) => !o && setDialog(null)} editing={dialog?.editing ?? null} />
    </SettingsPageLayout>
  );
}
