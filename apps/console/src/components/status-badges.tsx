import { cn } from '@/lib/utils';
import type { ActionStatus, CasePriority, CaseStatus } from '@/lib/types/cases';
import type { LifecycleStatus, ReviewKind, ReviewStatus, Risk, ToolAccess, ToolType } from '@/lib/types/domain';

const pill = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap';

/** Adapted from the shared component library's live badge, extended with a paused state. */
export function LiveBadge({ status, className }: { status: LifecycleStatus; className?: string }) {
  return (
    <span
      className={cn(
        pill,
        status === 'live' && 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
        status === 'draft' && 'border-border bg-muted text-muted-foreground',
        status === 'paused' && 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
        className,
      )}
    >
      {status === 'live' ? (
        <span className="relative flex size-1.5">
          <span className="absolute inline-flex size-1.5 animate-ping rounded-full bg-emerald-400 opacity-60" />
          <span className="relative inline-flex size-1.5 rounded-full bg-emerald-500" />
        </span>
      ) : (
        <span className={cn('inline-flex size-1.5 rounded-full', status === 'paused' ? 'bg-amber-500' : 'bg-muted-foreground/60')} />
      )}
      {status === 'live' ? 'Live' : status === 'draft' ? 'Draft' : 'Paused'}
    </span>
  );
}

const RISK: Record<Risk, string> = {
  critical: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  high: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
  medium: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300',
  low: 'border-border bg-muted text-muted-foreground',
};

export function RiskBadge({ risk }: { risk: Risk }) {
  return <span className={cn(pill, 'capitalize', RISK[risk])}>{risk}</span>;
}

const STATUS: Record<ReviewStatus, { label: string; cls: string; dot: string }> = {
  pending: { label: 'Pending', cls: 'border-border bg-card', dot: 'bg-amber-500' },
  in_review: { label: 'In review', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300', dot: 'bg-sky-500' },
  approved: { label: 'Approved', cls: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300', dot: 'bg-emerald-500' },
  rejected: { label: 'Rejected', cls: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300', dot: 'bg-red-500' },
  returned: { label: 'Returned to agent', cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
};

export function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  const s = STATUS[status];
  return (
    <span className={cn(pill, s.cls)}>
      <span className={cn('size-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  );
}

export const KIND_LABEL: Record<ReviewKind, string> = {
  approval: 'Approval',
  exception: 'Exception',
  escalation: 'Escalation',
  policy_override: 'Policy override',
  publish_request: 'Publish request',
  model_validation: 'Model validation',
};

const ACCESS: Record<ToolAccess, { label: string; cls: string }> = {
  read: { label: 'Read', cls: 'border-border bg-muted text-muted-foreground' },
  write: { label: 'Write', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300' },
  money_movement: { label: 'Moves money', cls: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300' },
};

export function AccessBadge({ access }: { access: ToolAccess }) {
  return <span className={cn(pill, ACCESS[access].cls)}>{ACCESS[access].label}</span>;
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.85 ? 'bg-emerald-500' : value >= 0.7 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-muted">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-xs tabular-nums text-muted-foreground">{pct}%</span>
    </div>
  );
}

const TOOL_TYPE: Record<ToolType, string> = {
  http: 'border-chart-2/40 text-chart-2',
  code: 'border-chart-3/40 text-chart-3',
  mcp: 'border-primary/40 text-primary',
};

export function ToolTypeBadge({ type }: { type: ToolType }) {
  return <span className={cn('rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase', TOOL_TYPE[type])}>{type}</span>;
}

export function SlaText({ minutes, open, paused }: { minutes: number; open: boolean; /** Clock stopped while waiting on the customer. */ paused?: boolean }) {
  if (!open) return <span className="text-xs text-muted-foreground">—</span>;
  if (paused) return <span className="text-xs whitespace-nowrap text-muted-foreground">Paused · waiting on customer</span>;
  const span = (m: number) => (m < 60 ? `${m}m` : m < 60 * 48 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`);
  const label = minutes < 0 ? `${span(Math.abs(minutes))} overdue` : `${span(minutes)} left`;
  return (
    <span
      className={cn(
        'text-xs whitespace-nowrap tabular-nums',
        minutes < 0 ? 'font-semibold text-red-600 dark:text-red-400' : minutes < 60 ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground',
      )}
    >
      {label}
    </span>
  );
}

const CASE_STATUS: Record<CaseStatus, { label: string; cls: string; dot: string }> = {
  new: { label: 'New', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300', dot: 'bg-sky-500' },
  in_progress: { label: 'In progress', cls: 'border-border bg-card', dot: 'bg-primary' },
  waiting_approval: { label: 'Waiting on approval', cls: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300', dot: 'bg-amber-500' },
  waiting_customer: { label: 'Waiting on customer', cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
  closed: { label: 'Closed', cls: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300', dot: 'bg-emerald-500' },
};
export const CASE_STATUS_LABEL = Object.fromEntries(Object.entries(CASE_STATUS).map(([k, v]) => [k, v.label])) as Record<CaseStatus, string>;

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  const s = CASE_STATUS[status];
  return (
    <span className={cn(pill, s.cls)}>
      <span className={cn('size-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  );
}

const PRIORITY: Record<CasePriority, string> = {
  urgent: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300',
  high: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
  normal: 'border-border bg-card text-foreground',
  low: 'border-border bg-muted text-muted-foreground',
};

export function PriorityBadge({ priority }: { priority: CasePriority }) {
  return <span className={cn(pill, 'capitalize', PRIORITY[priority])}>{priority}</span>;
}

const ACTION_STATUS: Record<ActionStatus, { label: string; cls: string }> = {
  drafted: { label: 'Needs approval', cls: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300' },
  awaiting_second: { label: 'Needs second approver', cls: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300' },
  approved: { label: 'Approved', cls: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' },
  executed: { label: 'Done', cls: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' },
  rejected: { label: 'Rejected', cls: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300' },
  failed: { label: 'Failed', cls: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300' },
};

/** A drafted action that needs no approval runs on its own, so it reads as "Ready" rather than "Needs approval". */
export function ActionStatusBadge({ status, needsApproval }: { status: ActionStatus; needsApproval: boolean }) {
  const s = status === 'drafted' && !needsApproval ? { label: 'Ready', cls: 'border-border bg-muted text-muted-foreground' } : ACTION_STATUS[status];
  return <span className={cn(pill, s.cls)}>{s.label}</span>;
}
