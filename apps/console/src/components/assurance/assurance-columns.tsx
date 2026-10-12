import Link from 'next/link';
import type { ColumnDef } from '@tanstack/react-table';
import { Download } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { StopRowClick } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { RiskBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { facetFilterFn } from '@/hooks/use-list-params';
import { dateTime, ms, pct, plural, relativeTime } from '@/lib/format';
import type { AssuranceGate, AssuranceJudge, AssuranceRun, AssuranceSuite, EvidenceBundleRow } from '@/lib/types/assurance';
import type { Risk } from '@/lib/types/domain';

import { AssetCell, GateStepChip, TRIGGER_LABEL } from './assurance-meta';

/** Rows carry their click handler so DataTableWithViews can open a sheet. */
export type Clickable<T> = T & { onRowClick?: (r: T) => void; rowTestId?: string };

const TIER_ORDER: Record<Risk, number> = { critical: 0, high: 1, medium: 2, low: 3 };
const tierColumn = <T extends { tier: Risk }>(): ColumnDef<T> => ({
  accessorKey: 'tier',
  header: ({ column }) => <DataTableColumnHeader column={column} title="Risk tier" />,
  cell: ({ row }) => <RiskBadge risk={row.original.tier} />,
  sortingFn: (a, b) => TIER_ORDER[a.original.tier] - TIER_ORDER[b.original.tier],
  filterFn: facetFilterFn,
});
const kindColumn = <T extends { asset: { kind: string } }>(): ColumnDef<T> => ({ id: 'kind', accessorFn: (r) => r.asset.kind, header: 'Kind', filterFn: facetFilterFn });
const usd = (n: number) => `$${n.toFixed(2)}`;

export const suiteColumns: ColumnDef<Clickable<AssuranceSuite>>[] = [
  { id: 'name', accessorFn: (r) => r.asset.name, header: ({ column }) => <DataTableColumnHeader column={column} title="Asset" />, cell: ({ row }) => <AssetCell asset={row.original.asset} />, enableHiding: false },
  kindColumn(),
  {
    accessorKey: 'cases',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Cases" />,
    cell: ({ row }) => (
      <div className="whitespace-nowrap tabular-nums">
        {row.original.cases}
        {row.original.draftCases > 0 && (
          <Badge variant="outline" className="ml-2 border-warning/40 text-warning-text" data-testid="suite-draft-count">
            +{plural(row.original.draftCases, 'draft case')}
          </Badge>
        )}
      </div>
    ),
  },
  {
    id: 'passRate',
    accessorFn: (r) => r.passRate ?? -1,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Last run vs live" />,
    cell: ({ row }) => {
      const r = row.original;
      if (r.passRate === null) return <span className="text-xs text-muted-foreground">Not run</span>;
      return (
        <span className="whitespace-nowrap tabular-nums">
          <span className={r.failing ? 'font-medium text-destructive' : 'font-medium'}>{pct(r.passRate)}</span>
          <span className="text-muted-foreground"> vs {r.livePassRate === null ? '—' : pct(r.livePassRate)}</span>
        </span>
      );
    },
  },
  {
    accessorKey: 'regressions',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Regressions" />,
    cell: ({ row }) => <span className={row.original.regressions ? 'font-medium text-destructive tabular-nums' : 'tabular-nums text-muted-foreground'}>{row.original.regressions ?? '—'}</span>,
  },
  tierColumn(),
  { id: 'result', accessorFn: (r) => (r.passRate === null ? 'not_run' : r.failing ? 'failing' : 'passing'), header: 'Result', filterFn: facetFilterFn },
  { accessorKey: 'owner', header: ({ column }) => <DataTableColumnHeader column={column} title="Owner" />, cell: ({ row }) => <span className="text-xs">{row.original.owner}</span> },
  { accessorKey: 'lastRunAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last run" />, cell: ({ row }) => <span className="whitespace-nowrap text-xs">{row.original.lastRunAt ? relativeTime(row.original.lastRunAt) : '—'}</span> },
];

export const runColumns: ColumnDef<AssuranceRun>[] = [
  { id: 'name', accessorFn: (r) => r.asset.name, header: ({ column }) => <DataTableColumnHeader column={column} title="Asset" />, cell: ({ row }) => <AssetCell asset={row.original.asset} sub={`v${row.original.version}`} />, enableHiding: false },
  kindColumn(),
  { accessorKey: 'trigger', header: 'Trigger', cell: ({ row }) => <span className="whitespace-nowrap text-xs">{TRIGGER_LABEL[row.original.trigger]}</span>, filterFn: facetFilterFn },
  {
    accessorKey: 'passRate',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Pass rate" />,
    cell: ({ row }) => (
      <span className="whitespace-nowrap tabular-nums">
        {pct(row.original.passRate)} <span className="text-xs text-muted-foreground">{row.original.passed} of {row.original.total}</span>
      </span>
    ),
  },
  { accessorKey: 'regressions', header: ({ column }) => <DataTableColumnHeader column={column} title="Regressions" />, cell: ({ row }) => <span className={row.original.regressions ? 'font-medium text-destructive tabular-nums' : 'tabular-nums text-muted-foreground'}>{row.original.regressions}</span> },
  { accessorKey: 'durationMs', header: ({ column }) => <DataTableColumnHeader column={column} title="Duration" />, cell: ({ row }) => <span className="whitespace-nowrap tabular-nums text-xs">{ms(row.original.durationMs)}</span> },
  { accessorKey: 'costUsd', header: ({ column }) => <DataTableColumnHeader column={column} title="Cost" />, cell: ({ row }) => <span className="tabular-nums text-xs">{usd(row.original.costUsd)}</span> },
  { accessorKey: 'ranAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Ran" />, cell: ({ row }) => <span className="whitespace-nowrap text-xs">{relativeTime(row.original.ranAt)}</span> },
  {
    id: 'review',
    header: 'Review',
    cell: ({ row }) =>
      row.original.reviewId ? (
        <Link className="text-xs whitespace-nowrap underline underline-offset-2" href={`/reviews?review=${row.original.reviewId}`}>
          {row.original.reviewId}
        </Link>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
      ),
  },
];

const STATUS_LABEL: Record<AssuranceGate['reviewStatus'], string> = { pending: 'Waiting', in_review: 'In review', approved: 'Approved', rejected: 'Rejected', returned: 'Returned' };

export const gateColumns: ColumnDef<AssuranceGate>[] = [
  { id: 'name', accessorFn: (r) => r.asset.name, header: ({ column }) => <DataTableColumnHeader column={column} title="Publish request" />, cell: ({ row }) => <AssetCell asset={row.original.asset} sub={`${row.original.fromVersion === null ? 'first publish, ' : `v${row.original.fromVersion} → `}v${row.original.toVersion} · ${row.original.requestedBy}`} />, enableHiding: false },
  tierColumn(),
  {
    id: 'steps',
    header: 'Gate steps',
    cell: ({ row }) => (
      <div className="flex max-w-xl flex-wrap gap-1" data-testid={`gate-steps-${row.original.reviewId}`}>
        {row.original.steps.map((s) => (
          <GateStepChip key={s.step} step={s} />
        ))}
      </div>
    ),
  },
  {
    id: 'result',
    accessorFn: (r) => (r.blocked ? 'blocked' : r.reviewStatus === 'pending' || r.reviewStatus === 'in_review' ? 'ready' : 'decided'),
    header: 'Status',
    cell: ({ row }) => (row.original.blocked ? <span className="text-xs font-medium whitespace-nowrap text-destructive">Blocked</span> : <span className="text-xs whitespace-nowrap">{STATUS_LABEL[row.original.reviewStatus]}</span>),
    filterFn: facetFilterFn,
  },
  { accessorKey: 'requestedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Requested" />, cell: ({ row }) => <span className="whitespace-nowrap text-xs">{relativeTime(row.original.requestedAt)}</span> },
  {
    id: 'review',
    header: 'Review',
    cell: ({ row }) => (
      <Link className="text-xs whitespace-nowrap underline underline-offset-2" href={`/reviews?review=${row.original.reviewId}`}>
        {row.original.reviewId}
      </Link>
    ),
  },
];

export const evidenceColumns = (onExport: (b: EvidenceBundleRow) => void, exportingId: string | null): ColumnDef<EvidenceBundleRow>[] => [
  { id: 'name', accessorFn: (r) => r.asset.name, header: ({ column }) => <DataTableColumnHeader column={column} title="Asset" />, cell: ({ row }) => <AssetCell asset={row.original.asset} sub={`v${row.original.version}${row.original.live ? ' · live' : ''}`} />, enableHiding: false },
  kindColumn(),
  { accessorKey: 'digest', header: 'Digest', cell: ({ row }) => <code className="font-mono text-xs" title={row.original.digest}>{row.original.digest.slice(0, 19)}…</code> },
  { id: 'approvers', accessorFn: (r) => r.approvers.join(', '), header: 'Approvers', cell: ({ row }) => <span className="text-xs">{row.original.approvers.join(', ')}</span> },
  { accessorKey: 'sealedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Sealed" />, cell: ({ row }) => <span className="whitespace-nowrap text-xs">{dateTime(row.original.sealedAt)}</span> },
  {
    id: 'actions',
    header: '',
    cell: ({ row }) => (
      <StopRowClick>
        <LoadingButton variant="outline" size="sm" isLoading={exportingId === row.original.id} disabled={!!exportingId} onClick={() => onExport(row.original)}>
          <Download className="size-4" /> Export
        </LoadingButton>
      </StopRowClick>
    ),
  },
];

export const judgeColumns: ColumnDef<Clickable<AssuranceJudge>>[] = [
  {
    id: 'name',
    accessorFn: (r) => r.name,
    header: ({ column }) => <DataTableColumnHeader column={column} title="Judge" />,
    cell: ({ row }) => (
      <div className="max-w-72" title={row.original.criterion}>
        <div className="truncate font-medium">{row.original.name}</div>
        <div className="truncate text-xs text-muted-foreground">{row.original.criterion}</div>
      </div>
    ),
    enableHiding: false,
  },
  { accessorKey: 'model', header: 'Judge model', cell: ({ row }) => <code className="font-mono text-xs">{row.original.model}</code> },
  { accessorKey: 'promptVersion', header: 'Prompt', cell: ({ row }) => <span className="tabular-nums">v{row.original.promptVersion}</span> },
  { accessorKey: 'calibrationSize', header: ({ column }) => <DataTableColumnHeader column={column} title="Calibration set" />, cell: ({ row }) => <span className="tabular-nums">{plural(row.original.calibrationSize, 'case')}</span> },
  {
    accessorKey: 'agreement',
    header: ({ column }) => <DataTableColumnHeader column={column} title="Agreement" />,
    cell: ({ row }) => (
      <span className={row.original.agreement < row.original.minAgreement ? 'font-medium text-destructive tabular-nums' : 'tabular-nums'}>
        {pct(row.original.agreement)}
        {row.original.agreement < row.original.minAgreement && <span className="ml-1 text-xs">advisory only</span>}
      </span>
    ),
  },
  { accessorKey: 'lastRecalibratedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Last recalibrated" />, cell: ({ row }) => <span className="whitespace-nowrap text-xs">{relativeTime(row.original.lastRecalibratedAt)}</span> },
];
