'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import type { DateRange } from 'react-day-picker';
import { CheckCircle2, Clock, SquareTerminal, XCircle } from 'lucide-react';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { ListEmpty, QueryError } from '@/components/shared/query-states';
import { serverPagination } from '@/components/shared/server-pagination';
import { useToolCalls } from '@/hooks/governance-queries';
import { facetFilterFn, useListParams } from '@/hooks/use-list-params';
import type { CallStatus, ToolCallFilters, ToolCallRow } from '@/lib/types/governance';

const RESULT: Record<CallStatus, { label: string; icon: typeof CheckCircle2; tone: string }> = {
  ok: { label: 'Ran', icon: CheckCircle2, tone: 'text-success' },
  replayed: { label: 'Ran', icon: CheckCircle2, tone: 'text-success' },
  running: { label: 'Running', icon: Clock, tone: 'text-muted-foreground' },
  awaiting_approval: { label: 'Waiting for approval', icon: Clock, tone: 'text-warning' },
  denied: { label: 'Refused', icon: XCircle, tone: 'text-destructive' },
  error: { label: 'Failed', icon: XCircle, tone: 'text-destructive' },
};

type Row = ToolCallRow & { who: string; assistant: string; tool: string; result: string; onRowClick: () => void; rowTestId: string };

const time = (iso: string) => new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const dayAfter = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).toISOString();
const dayOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).toISOString();

const columns: ColumnDef<Row>[] = [
  { accessorKey: 'at', header: 'When', cell: ({ row }) => <span className="tabular-nums">{time(row.original.at)}</span> },
  { accessorKey: 'who', header: 'Who' },
  { accessorKey: 'assistant', header: 'Assistant', filterFn: facetFilterFn },
  // The tool's own name: what the server's search matches, so the table never hides a row it returned.
  { accessorKey: 'target', header: 'Tool name', enableHiding: true },
  { accessorKey: 'tool', header: 'Tool' },
  {
    accessorKey: 'result',
    header: 'Result',
    filterFn: facetFilterFn,
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

/** Every call made through one link, newest first, from the one call log agents and workflows use; a row opens it. */
export function CallsTab({ linkId }: { linkId: string }) {
  const [range, setRange] = React.useState<DateRange | undefined>();
  const [openId, setOpenId] = React.useState<string | null>(null);
  const list = useListParams<ToolCallFilters>('target', 20);
  const q = useToolCalls({
    ...list.params,
    filters: {
      ...list.params.filters,
      link: [linkId],
      ...(range?.from ? { since: [dayOf(range.from)] } : {}),
      ...(range?.to ?? range?.from ? { until: [dayAfter((range.to ?? range.from)!)] } : {}),
    },
  });
  if (q.isPending && !q.data) return <PageSkeleton statCards={0} tableRows={4} />;
  if (q.isError && !q.data) return <QueryError what="the link’s calls" error={q.error} onRetry={() => void q.refetch()} retrying={q.isFetching} />;
  const rows: Row[] = (q.data?.data ?? []).map((c) => ({
    ...c,
    who: c.subject?.name ?? c.actingFor ?? '',
    // The name the person allowed on the consent page, or what an assistant without a token calls itself.
    assistant: c.clientName ?? 'Unnamed assistant',
    tool: [c.app, c.title ?? c.target].filter(Boolean).join(' · '),
    result: RESULT[c.status].label,
    onRowClick: () => setOpenId(c.id),
    rowTestId: `mcp-call-row-${c.id}`,
  }));
  const open = rows.find((r) => r.id === openId);
  // Every value the server counted, with its count, for the result and assistant the other filters leave.
  const facets = q.data?.facets ?? {};
  const optionsOf = (key: 'assistant' | 'result', fixed: string[] = []) =>
    [...new Set([...fixed, ...Object.keys(facets[key] ?? {}), ...(list.params.filters?.[key] ?? [])])].map((v) => ({ label: v, value: v, count: facets[key]?.[v] ?? 0 }));
  return (
    <div data-testid="mcp-link-calls">
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        searchColumn="target"
        searchPlaceholder="Search calls by tool name…"
        initialColumnVisibility={{ target: false }}
        hideViewSwitcher
        onColumnFiltersChange={list.onColumnFiltersChange}
        serverPagination={serverPagination(list, q)}
        filters={[
          { column: 'result', title: 'Result', options: optionsOf('result', ['Ran', 'Running', 'Refused', 'Failed']) },
          { column: 'assistant', title: 'Assistant', options: optionsOf('assistant') },
        ]}
        dateRange={{ value: range, onChange: setRange, placeholder: 'Any day' }}
        emptyState={<ListEmpty icon={SquareTerminal} noun="calls" filtered={!!range || list.isFiltered} onClear={() => setRange(undefined)} description="Calls made through this link appear here, with who made them and from which assistant." />}
      />
      <DetailSheet open={!!open} onOpenChange={(o) => !o && setOpenId(null)} title={open?.tool ?? ''} description={open ? time(open.at) : undefined} testId="mcp-call-sheet">
        {open && (
          <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Who</dt>
            <dd>{open.who}</dd>
            <dt className="text-muted-foreground">Assistant</dt>
            <dd>{open.assistant}</dd>
            <dt className="text-muted-foreground">Result</dt>
            <dd>{open.result}{open.denyReason ? `: ${open.denyReason}` : ''}</dd>
            <dt className="text-muted-foreground">Time</dt>
            <dd className="tabular-nums">{open.latencyMs ? `${(open.latencyMs / 1000).toFixed(1)} s` : '—'}</dd>
            <dt className="text-muted-foreground">Call id</dt>
            <dd className="break-all font-mono text-xs">{open.id}</dd>
            {open.errorMessage && (
              <>
                <dt className="text-muted-foreground">Error</dt>
                <dd>{open.errorMessage}</dd>
              </>
            )}
          </dl>
        )}
      </DetailSheet>
    </div>
  );
}
