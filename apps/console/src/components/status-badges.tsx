import { cn } from '@/lib/utils';
import type { ActionStatus, CasePriority, CaseStatus } from '@/lib/types/cases';
import type { AgentAvailability, AgentVersionState, GrantAccess, LifecycleStatus, ReviewKind, ReviewStatus, Risk, ToolType } from '@/lib/types/domain';

const pill = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap';

// The Workflows list also sends in_review (a first version waiting in Reviews) and archived; each reads as itself.
const LIVE_LABEL: Record<LifecycleStatus | 'in_review' | 'archived', string> = { live: 'Live', draft: 'Draft', paused: 'Paused', in_review: 'In review', archived: 'Archived' };

/** Adapted from the shared component library's live badge, extended with paused, in review and archived states. */
export function LiveBadge({ status, className }: { status: keyof typeof LIVE_LABEL; className?: string }) {
  return (
    <span
      className={cn(
        pill,
        status === 'live' && 'border-success/40 bg-success/10 text-success-text',
        (status === 'draft' || status === 'archived') && 'border-border bg-muted text-muted-foreground',
        (status === 'paused' || status === 'in_review') && 'border-warning/40 bg-warning/10 text-warning-text',
        className,
      )}
    >
      {status === 'live' ? (
        <span className="relative flex size-1.5">
          <span className="absolute inline-flex size-1.5 animate-ping rounded-full bg-success opacity-60" />
          <span className="relative inline-flex size-1.5 rounded-full bg-success" />
        </span>
      ) : (
        <span className={cn('inline-flex size-1.5 rounded-full', status === 'paused' || status === 'in_review' ? 'bg-warning' : 'bg-muted-foreground/60')} />
      )}
      {LIVE_LABEL[status] ?? status}
    </span>
  );
}

const RISK: Record<Risk, string> = {
  critical: 'border-destructive/40 bg-destructive/10 text-destructive',
  high: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
  medium: 'border-warning/40 bg-warning/10 text-warning-text',
  low: 'border-border bg-muted text-muted-foreground',
};

export function RiskBadge({ risk }: { risk: Risk }) {
  return <span className={cn(pill, 'capitalize', RISK[risk])}>{risk}</span>;
}

const STATUS: Record<ReviewStatus, { label: string; cls: string; dot: string }> = {
  pending: { label: 'Pending', cls: 'border-border bg-card', dot: 'bg-warning' },
  in_review: { label: 'In review', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300', dot: 'bg-sky-500' },
  approved: { label: 'Approved', cls: 'border-success/40 bg-success/10 text-success-text', dot: 'bg-success' },
  rejected: { label: 'Rejected', cls: 'border-destructive/40 bg-destructive/10 text-destructive', dot: 'bg-destructive' },
  returned: { label: 'Returned to agent', cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
};

export function ReviewStatusBadge({ status }: { status: ReviewStatus }) {
  // A review decided with one of a step's options comes back with that option as its status; shown as is.
  const s = STATUS[status] ?? { label: status, cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground/50' };
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
  agent_publish: 'Agent publish',
  model_validation: 'Model validation',
  skill_publish: 'Skill publish',
  template_submission: 'Template submission',
};

const ACCESS: Record<GrantAccess, { label: string; cls: string }> = {
  read: { label: 'Read', cls: 'border-border bg-muted text-muted-foreground' },
  write: { label: 'Write', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300' },
  workflow: { label: 'Workflow', cls: 'border-border bg-background text-foreground' },
};

export function AccessBadge({ access }: { access: GrantAccess }) {
  return <span className={cn(pill, ACCESS[access].cls)}>{ACCESS[access].label}</span>;
}

/** A field's confidence as a small badge, coloured by the same thresholds as ConfidenceBar; nothing when not scored. */
export function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  const tone = value >= 0.85 ? 'border-success/40 bg-success/10 text-success-text' : value >= 0.7 ? 'border-warning/50 bg-warning/10 text-warning-text' : 'border-destructive/40 bg-destructive/10 text-destructive';
  return <span className={cn('inline-flex w-fit items-center rounded-md border px-1.5 py-0.5 text-xs font-medium tabular-nums', tone)}>{Math.round(value * 100)}%</span>;
}

export function ConfidenceBar({ value }: { value: number | null }) {
  // A step no model scored has no confidence; showing 0% would read as a model that was sure it was wrong.
  if (value === null) return <span className="text-xs text-muted-foreground">Not scored</span>;
  const pct = Math.round(value * 100);
  const color = value >= 0.85 ? 'bg-success' : value >= 0.7 ? 'bg-warning' : 'bg-destructive';
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
  workflow: 'border-chart-4/40 text-chart-4',
};

export function ToolTypeBadge({ type }: { type: ToolType }) {
  return <span className={cn('rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase', TOOL_TYPE[type])}>{type}</span>;
}

export function SlaText({ minutes, open, paused }: { /** Null when nothing has a deadline (a decided review). */ minutes: number | null; open: boolean; /** Clock stopped while waiting on the customer. */ paused?: boolean }) {
  if (!open || minutes == null) return <span className="text-xs text-muted-foreground">—</span>;
  if (paused) return <span className="text-xs whitespace-nowrap text-muted-foreground">Paused · waiting on customer</span>;
  const span = (m: number) => (m < 60 ? `${m}m` : m < 60 * 48 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${Math.floor(m / 1440)}d ${Math.floor((m % 1440) / 60)}h`);
  const label = minutes < 0 ? `${span(Math.abs(minutes))} overdue` : `${span(minutes)} left`;
  return (
    <span
      className={cn(
        'text-xs whitespace-nowrap tabular-nums',
        minutes < 0 ? 'font-semibold text-destructive' : minutes < 60 ? 'text-warning-text' : 'text-muted-foreground',
      )}
    >
      {label}
    </span>
  );
}

const CASE_STATUS: Record<CaseStatus, { label: string; cls: string; dot: string }> = {
  new: { label: 'New', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300', dot: 'bg-sky-500' },
  in_progress: { label: 'In progress', cls: 'border-border bg-card', dot: 'bg-primary' },
  waiting_approval: { label: 'Waiting on approval', cls: 'border-warning/40 bg-warning/10 text-warning-text', dot: 'bg-warning' },
  waiting_customer: { label: 'Waiting on customer', cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
  closed: { label: 'Closed', cls: 'border-success/40 bg-success/10 text-success-text', dot: 'bg-success' },
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
  urgent: 'border-destructive/40 bg-destructive/10 text-destructive',
  high: 'border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300',
  normal: 'border-border bg-card text-foreground',
  low: 'border-border bg-muted text-muted-foreground',
};

export function PriorityBadge({ priority }: { priority: CasePriority }) {
  return <span className={cn(pill, 'capitalize', PRIORITY[priority])}>{priority}</span>;
}

const ACTION_STATUS: Record<ActionStatus, { label: string; cls: string }> = {
  drafted: { label: 'Needs approval', cls: 'border-warning/40 bg-warning/10 text-warning-text' },
  awaiting_second: { label: 'Needs second reviewer', cls: 'border-warning/40 bg-warning/10 text-warning-text' },
  approved: { label: 'Approved', cls: 'border-success/40 bg-success/10 text-success-text' },
  executed: { label: 'Done', cls: 'border-success/40 bg-success/10 text-success-text' },
  rejected: { label: 'Rejected', cls: 'border-destructive/40 bg-destructive/10 text-destructive' },
  failed: { label: 'Failed', cls: 'border-destructive/40 bg-destructive/10 text-destructive' },
};

/** A drafted action that needs no approval runs on its own, so it reads as "Ready" rather than "Needs approval". */
export function ActionStatusBadge({ status, needsApproval }: { status: ActionStatus; needsApproval: boolean }) {
  const s = status === 'drafted' && !needsApproval ? { label: 'Ready', cls: 'border-border bg-muted text-muted-foreground' } : ACTION_STATUS[status];
  return <span className={cn(pill, s.cls)}>{s.label}</span>;
}

const AGENT_VERSION_STATE: Record<AgentVersionState, { label: string; cls: string }> = {
  draft: { label: 'Draft', cls: 'border-border bg-muted text-muted-foreground' },
  in_review: { label: 'In review', cls: 'border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300' },
  published: { label: 'Published', cls: 'border-success/40 bg-success/10 text-success-text' },
  superseded: { label: 'Superseded', cls: 'border-border bg-transparent text-muted-foreground' },
  rejected: { label: 'Rejected', cls: 'border-destructive/40 bg-destructive/10 text-destructive' },
};

/** State of an agent version: drafts publish through an `agent_publish` review before workflows can pin them. */
export function AgentVersionBadge({ state, testId }: { state: AgentVersionState; testId?: string }) {
  const s = AGENT_VERSION_STATE[state];
  return (
    <span className={cn(pill, s.cls)} data-testid={testId}>
      {s.label}
    </span>
  );
}

export const AVAILABILITY_LABEL: Record<AgentAvailability, string> = { published: 'Published', not_published: 'Not published', paused: 'Paused' };
const AVAILABILITY_CLS: Record<AgentAvailability, string> = {
  published: 'border-success/40 bg-success/10 text-success-text',
  not_published: 'border-border bg-muted text-muted-foreground',
  paused: 'border-warning/40 bg-warning/10 text-warning-text',
};

/** Whether workflows can pin the agent and new runs use it: published, not published, or paused by an operator. */
export function AgentAvailabilityBadge({ availability }: { availability: AgentAvailability }) {
  return (
    <span className={cn(pill, AVAILABILITY_CLS[availability])} data-testid="agent-availability">
      {AVAILABILITY_LABEL[availability]}
    </span>
  );
}
