'use client';

import type { ColumnDef } from '@tanstack/react-table';
import { CheckCircle2, Clock, SquareTerminal, XCircle } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { useToolCalls } from '@/hooks/governance-queries';
import type { CallStatus, ToolCallRow } from '@/lib/types/governance';

const RESULT: Record<CallStatus, { label: string; icon: typeof CheckCircle2; tone: string }> = {
  ok: { label: 'Ran', icon: CheckCircle2, tone: 'text-success' },
  replayed: { label: 'Ran', icon: CheckCircle2, tone: 'text-success' },
  running: { label: 'Running', icon: Clock, tone: 'text-muted-foreground' },
  awaiting_approval: { label: 'Waiting for approval', icon: Clock, tone: 'text-warning' },
  denied: { label: 'Refused', icon: XCircle, tone: 'text-destructive' },
  error: { label: 'Failed', icon: XCircle, tone: 'text-destructive' },
};

type Row = ToolCallRow & { who: string; assistant: string; tool: string; result: string };

const time = (iso: string) => new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

const columns: ColumnDef<Row>[] = [
  { accessorKey: 'at', header: 'When', cell: ({ row }) => <span className="tabular-nums">{time(row.original.at)}</span> },
  { accessorKey: 'who', header: 'Who' },
  { accessorKey: 'assistant', header: 'Assistant' },
  { accessorKey: 'tool', header: 'Tool' },
  {
    accessorKey: 'result',
    header: 'Result',
    filterFn: (row, id, value: string[]) => value.includes(row.getValue(id)),
    cell: ({ row }) => {
      const r = RESULT[row.original.status];
      const Icon = r.icon;
      return (
        <span className="flex items-center gap-1.5 text-sm">
          <Icon className={`size-3.5 ${r.tone}`} aria-hidden />
          {r.label}
          {row.original.denyReason ? <span className="text-muted-foreground">: {row.original.denyReason}</span> : null}
        </span>
      );
    },
  },
  { id: 'latency', header: 'Time', cell: ({ row }) => <span className="tabular-nums">{row.original.status === 'ok' ? `${(row.original.latencyMs / 1000).toFixed(1)} s` : '—'}</span> },
];

/** Every call made through one link, newest first, from the one call log agents and workflows use. */
export function CallsTab({ linkId }: { linkId: string }) {
  const q = useToolCalls({ page: 1, pageSize: 100, filters: { link: [linkId] } });
  if (q.isPending) return <PageSkeleton statCards={0} tableRows={4} />;
  if (q.isError && !q.data) return <QueryError what="the link’s calls" error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} />;
  const rows: Row[] = (q.data?.data ?? []).map((c) => ({
    ...c,
    who: c.actingFor ?? c.subject?.name ?? '',
    // A signed-in assistant is named by the client a person allowed; one that sent no token by what it says it is.
    assistant: c.clientName ?? (c.clientId ? 'Signed-in assistant' : 'Unnamed assistant'),
    tool: [c.app, c.title ?? c.target].filter(Boolean).join(' · '),
    result: RESULT[c.status].label,
  }));
  return (
    <div data-testid="mcp-link-calls">
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        searchColumn="tool"
        searchPlaceholder="Search calls by tool…"
        hideViewSwitcher
        hidePaginationOnOnePage
        filters={[{ column: 'result', title: 'Result', options: [...new Set(Object.values(RESULT).map((r) => r.label))].map((l) => ({ label: l, value: l })) }]}
        emptyState={<ListEmpty icon={SquareTerminal} noun="calls" filtered={false} description="Calls made through this link appear here, with who made them and from which assistant." />}
      />
    </div>
  );
}
