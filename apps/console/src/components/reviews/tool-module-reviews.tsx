'use client';

import * as React from 'react';
import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { ShieldCheck } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { KeyValues } from '@/components/shared/surface';
import { ModuleReviewDecision } from '@/components/tools/module-review-decision';
import { useToolModules } from '@/hooks/tool-module-queries';
import { relativeTime } from '@/lib/format';
import type { ToolModule } from '@/lib/types/tool-modules';

type Row = ToolModule & { onRowClick: (m: ToolModule) => void };

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: 'displayName',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Module" />,
    cell: ({ row }) => (
      <div className="min-w-48">
        <div className="font-medium">{row.original.displayName}</div>
        <div className="text-xs text-muted-foreground">
          {row.original.system} · {row.original.ownerTeam}
        </div>
      </div>
    ),
    enableHiding: false,
  },
  { id: 'version', header: 'Version', cell: ({ row }) => <span className="font-mono text-sm">v{row.original.pendingReview?.version}</span> },
  { id: 'requestedBy', header: 'Requested by', cell: ({ row }) => <span className="text-sm">{row.original.pendingReview?.requestedBy}</span> },
  { id: 'requestedAt', header: 'Requested', cell: ({ row }) => <span className="text-sm whitespace-nowrap text-muted-foreground">{row.original.pendingReview ? relativeTime(row.original.pendingReview.requestedAt) : ''}</span> },
];

/**
 * Tool modules waiting on Security, from tools-service's security_review view: a list of its own beside the agents
 * queue, not merged into it (that would join two services' lists in the browser). A row opens the same decision form
 * the module page shows.
 */
export function ToolModuleReviews() {
  const query = useToolModules({ page: 1, pageSize: 100, view: 'security_review' });
  const [openId, setOpenId] = React.useState<string | null>(null);
  const rows: Row[] = (query.data?.data ?? []).map((m) => ({ ...m, onRowClick: (x) => setOpenId(x.id) }));
  const open = rows.find((r) => r.id === openId);

  if (query.isError && !query.data) return <QueryError what="tool module reviews" onRetry={() => query.refetch()} retrying={query.isFetching} />;
  return (
    <div data-testid="tool-module-reviews">
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(m) => m.id}
        searchColumn="displayName"
        searchPlaceholder="Search modules…"
        hideViewSwitcher
        emptyState={<EmptyState icon={ShieldCheck} title="No module is waiting on Security" description="A module's owner requests a security review from its page; it appears here until Security decides." />}
      />
      <DetailSheet
        open={!!open}
        onOpenChange={(o) => !o && setOpenId(null)}
        title={open ? `${open.displayName} v${open.pendingReview?.version}` : ''}
        description="Security review"
      >
        {open?.pendingReview && (
          <div className="flex flex-col gap-4">
            <KeyValues
              rows={[
                ['Requested by', open.pendingReview.requestedBy],
                ['Requested', relativeTime(open.pendingReview.requestedAt)],
                ['Owner', open.ownerTeam],
                ['Operations', String(open.operationCount)],
              ]}
            />
            <Link href={`/tools/${open.id}`} className="text-sm text-primary underline-offset-4 hover:underline">
              Open the module to read its operations and changes
            </Link>
            <ModuleReviewDecision moduleId={open.id} review={open.pendingReview} onDecided={() => setOpenId(null)} />
          </div>
        )}
      </DetailSheet>
    </div>
  );
}
