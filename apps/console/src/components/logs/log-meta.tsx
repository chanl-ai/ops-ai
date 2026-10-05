import { Ban, Bot, CheckCircle2, Clock, Cpu, Database, ShieldCheck, User, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { ApprovalKind, AuditAction, AuditTargetType, CallApproval, CallOperation, CallStatus, GatewayKind } from '@/lib/types/governance';
import { cn } from '@/lib/utils';

export const GATEWAY_LABEL: Record<GatewayKind, string> = { data: 'Data gateway', ai: 'AI gateway' };
export const OPERATION_LABEL: Record<CallOperation, string> = { read: 'Read', write: 'Write', money_movement: 'Moves money', completion: 'Model call' };
export const APPROVAL_LABEL: Record<ApprovalKind, string> = { person: 'Person', policy: 'Policy', none: 'None' };
export const CALL_STATUS_LABEL: Record<CallStatus, string> = { ok: 'Succeeded', error: 'Failed', denied: 'Denied', awaiting_approval: 'Awaiting approval' };

export const options = <K extends string>(labels: Record<K, string>) => (Object.entries(labels) as [K, string][]).map(([value, label]) => ({ value, label }));

/** Model cost in CAD; model calls cost fractions of a cent, so small amounts keep four decimals. */
export const cad = (n: number) => n.toLocaleString('en-CA', { style: 'currency', currency: 'CAD', minimumFractionDigits: n < 1 ? 4 : 2, maximumFractionDigits: n < 1 ? 4 : 2 });

export function GatewayIcon({ gateway, className }: { gateway: GatewayKind; className?: string }) {
  const Icon = gateway === 'ai' ? Cpu : Database;
  return <Icon className={cn('size-3.5 shrink-0 text-muted-foreground', className)} aria-label={GATEWAY_LABEL[gateway]} />;
}

export function OperationBadge({ operation }: { operation: CallOperation }) {
  const tone = operation === 'money_movement' ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300' : operation === 'write' ? 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300' : '';
  return (
    <Badge variant="outline" className={cn('font-normal', tone)}>
      {OPERATION_LABEL[operation]}
    </Badge>
  );
}

export function ApprovalCell({ approval }: { approval: CallApproval }) {
  if (approval.kind === 'none') return <span className="text-xs text-muted-foreground">None · read</span>;
  if (approval.kind === 'policy')
    return (
      <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap">
        <ShieldCheck className="size-3.5 text-muted-foreground" /> {approval.policyName} · v{approval.policyVersion}
      </span>
    );
  if (!approval.tokenId)
    return (
      <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-amber-700 dark:text-amber-400">
        <Clock className="size-3.5" /> Waiting · {approval.reviewId}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap">
      <User className="size-3.5 text-muted-foreground" /> {approval.by}
    </span>
  );
}

const STATUS: Record<CallStatus, { icon: typeof CheckCircle2; cls: string }> = {
  ok: { icon: CheckCircle2, cls: 'text-emerald-700 dark:text-emerald-400' },
  error: { icon: XCircle, cls: 'text-red-600 dark:text-red-400' },
  denied: { icon: Ban, cls: 'text-red-600 dark:text-red-400' },
  awaiting_approval: { icon: Clock, cls: 'text-amber-700 dark:text-amber-400' },
};

export function CallStatusText({ status }: { status: CallStatus }) {
  const s = STATUS[status];
  return (
    <span className={cn('inline-flex items-center gap-1 text-xs font-medium whitespace-nowrap', s.cls)}>
      <s.icon className="size-3.5" /> {CALL_STATUS_LABEL[status]}
    </span>
  );
}

export const ACTION_LABEL: Record<AuditAction, string> = {
  created: 'Created',
  edited: 'Edited',
  published: 'Published',
  approved: 'Approved',
  rejected: 'Rejected',
  restored: 'Restored',
  deleted: 'Deleted',
  granted: 'Granted',
  revoked: 'Revoked',
  connected: 'Connected',
  login: 'Signed in',
};

export const TARGET_LABEL: Record<AuditTargetType, string> = {
  workflow: 'Workflow',
  agent: 'Agent',
  tool: 'Tool',
  knowledge_base: 'Knowledge base',
  source: 'Source',
  deployment: 'Deployment',
  gate: 'Gate',
  review: 'Review',
  access_grant: 'Access grant',
  role: 'Role',
  member: 'Member',
  api_key: 'API key',
  webhook: 'Webhook',
  mailbox: 'Mailbox',
  notifications: 'Notifications',
  session: 'Session',
  model: 'Model',
};

export function ActionBadge({ action }: { action: AuditAction }) {
  const tone =
    action === 'deleted' || action === 'revoked' || action === 'rejected'
      ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300'
      : action === 'published' || action === 'approved' || action === 'granted'
        ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
        : '';
  return (
    <Badge variant="outline" className={cn('font-normal', tone)}>
      {ACTION_LABEL[action]}
    </Badge>
  );
}

export function ActorCell({ kind, name, detail }: { kind: 'person' | 'workflow'; name: string; detail: string }) {
  const Icon = kind === 'workflow' ? Bot : User;
  return (
    <div className="flex max-w-48 min-w-40 items-start gap-2">
      <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-label={kind === 'workflow' ? 'Workflow identity' : 'Person'} />
      <div className="min-w-0">
        <div className="truncate text-sm" title={name}>
          {name}
        </div>
        <div className="truncate font-mono text-[11px] text-muted-foreground" title={detail}>
          {detail}
        </div>
      </div>
    </div>
  );
}
