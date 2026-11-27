'use client';

import type { LegacyColumnDef as ColumnDef } from '@tanstack/react-table/legacy';
import { Brain, Cpu, Eye } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { useConnectionCatalog } from '@/hooks/model-queries';
import { useProviderKeyModels } from '@/hooks/provider-key-queries';
import { keyWhere } from '@/lib/model-forms';
import type { CatalogModel, ProviderConnection } from '@/lib/types/models';

const tokens = (n: number | null) => (n === null ? 'Not listed' : n >= 1_000_000 ? `${n / 1_000_000}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n));
const price = (m: CatalogModel) => (m.inputPerMillion === null || m.outputPerMillion === null ? 'Not listed' : `$${m.inputPerMillion} / $${m.outputPerMillion}`);

const columns: ColumnDef<CatalogModel>[] = [
  { accessorKey: 'id', header: ({ column }) => <DataTableColumnHeader column={column} title="Model" />, cell: ({ row }) => <code className="font-mono text-xs">{row.original.id}</code>, enableHiding: false },
  {
    id: 'can',
    header: 'Can do',
    cell: ({ row }) => (
      <span className="flex flex-wrap gap-1">
        {row.original.reasoning && (
          <Badge variant="outline">
            <Brain /> Thinking
          </Badge>
        )}
        {row.original.images && (
          <Badge variant="outline">
            <Eye /> Vision
          </Badge>
        )}
        {!row.original.reasoning && !row.original.images && <span className="text-xs text-muted-foreground">None listed</span>}
      </span>
    ),
  },
  { accessorKey: 'context', header: 'Context', cell: ({ row }) => <span className="text-sm whitespace-nowrap">{tokens(row.original.context)}</span> },
  { id: 'price', header: 'Price per 1M tokens', cell: ({ row }) => <span className="text-xs whitespace-nowrap">{price(row.original)}</span> },
];

/**
 * The models a connection offers. A provider type the catalog holds shows what each can do, its context and price; one it
 * does not (an endpoint's own list) shows the ids its key reaches, read from the provider.
 */
export function ConnectionModelsSheet({ connection, onClose }: { connection: ProviderConnection | null; onClose: () => void }) {
  const catalog = useConnectionCatalog(connection?.id ?? null);
  const uncatalogued = !!connection && catalog.isSuccess && catalog.data.length === 0;
  const where = uncatalogued && connection?.keyRef ? keyWhere(connection.type, connection) : null;
  const listed = useProviderKeyModels(connection?.keyRef ?? '', where);
  const rows: CatalogModel[] = catalog.data?.length ? catalog.data : (listed.data ?? []).map((m) => ({ id: m.id, name: m.model ?? m.id, context: null, output: null, reasoning: false, images: false, inputPerMillion: null, outputPerMillion: null, knobs: [] }));
  const pending = catalog.isPending || (!!where && listed.isPending);
  const failed = catalog.isError ? catalog : listed.isError ? listed : null;
  return (
    <DetailSheet open={!!connection} onOpenChange={(o) => !o && onClose()} title={connection?.name ?? ''} description="Models this connection offers" testId="connection-models-sheet" widthClass="sm:max-w-3xl">
      {pending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : failed ? (
        <QueryError what="the connection’s models" onRetry={() => failed.refetch()} retrying={failed.isFetching} error={failed.error} testId="connection-models-error" />
      ) : (
        <DataTableWithViews
          columns={columns}
          data={rows}
          getRowId={(m) => m.id}
          searchColumn="id"
          searchPlaceholder="Search models…"
          hideViewSwitcher
          emptyState={<ListEmpty icon={Cpu} noun="models" filtered={false} description="The provider lists none for this connection. Check the key’s project or deployment." />}
        />
      )}
    </DetailSheet>
  );
}
