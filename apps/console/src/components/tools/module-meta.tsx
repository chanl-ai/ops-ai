import { Braces, Code2, Globe, Plug } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { AccessBadge } from '@/components/status-badges';
import type { ToolAccess } from '@/lib/types/domain';
import type { ApprovalStatus, BindingSource, CredentialKind, Environment, ModuleApprovalState, ModuleType, SubjectBinding } from '@/lib/types/tool-modules';
import { cn } from '@/lib/utils';

const pill = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap';

export const MODULE_TYPE: Record<ModuleType, { label: string; icon: LucideIcon; hint: string }> = {
  mcp: { label: 'MCP server', icon: Plug, hint: 'A remote MCP server; its tool list is the operation list' },
  openapi: { label: 'OpenAPI', icon: Braces, hint: 'Operations imported from an OpenAPI document' },
  http: { label: 'HTTP', icon: Globe, hint: 'Operations built one request at a time' },
  code: { label: 'Code', icon: Code2, hint: 'Functions run in the sandbox' },
};

export function ModuleTypeBadge({ type }: { type: ModuleType }) {
  const t = MODULE_TYPE[type];
  return (
    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap text-muted-foreground">
      <t.icon className="size-3.5" /> {t.label}
    </span>
  );
}

/** Square tile with the system's initials, the catalog card and record header identity mark. */
export function ModuleMark({ name, className }: { name: string; className?: string }) {
  const letters = name
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
  return <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-md border bg-muted text-xs font-semibold text-muted-foreground', className)}>{letters}</span>;
}

const APPROVAL_STATE: Record<ModuleApprovalState, { label: string; cls: string; dot: string }> = {
  draft: { label: 'Draft', cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
  approved: { label: 'Approved', cls: 'border-success/40 bg-success/10 text-success-text', dot: 'bg-success' },
  needs_approval: { label: 'Needs approval', cls: 'border-warning/40 bg-warning/10 text-warning-text', dot: 'bg-warning' },
  expiring: { label: 'Expiring', cls: 'border-warning/40 bg-warning/10 text-warning-text', dot: 'bg-warning' },
  expired: { label: 'Expired', cls: 'border-destructive/40 bg-destructive/10 text-destructive', dot: 'bg-destructive' },
};
export const APPROVAL_STATE_LABEL = Object.fromEntries(Object.entries(APPROVAL_STATE).map(([k, v]) => [k, v.label])) as Record<ModuleApprovalState, string>;

export function ApprovalStateBadge({ state }: { state: ModuleApprovalState }) {
  const s = APPROVAL_STATE[state];
  return (
    <span className={cn(pill, s.cls)}>
      <span className={cn('size-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  );
}

const APPROVAL_STATUS: Record<ApprovalStatus, { label: string; cls: string }> = {
  requested: { label: 'Requested', cls: 'border-warning/40 bg-warning/10 text-warning-text' },
  approved: { label: 'Approved', cls: 'border-success/40 bg-success/10 text-success-text' },
  rejected: { label: 'Rejected', cls: 'border-destructive/40 bg-destructive/10 text-destructive' },
  expired: { label: 'Expired', cls: 'border-destructive/40 bg-destructive/10 text-destructive' },
  revoked: { label: 'Revoked', cls: 'border-border bg-muted text-muted-foreground' },
};

export function ApprovalStatusBadge({ status }: { status: ApprovalStatus }) {
  return <span className={cn(pill, APPROVAL_STATUS[status].cls)}>{APPROVAL_STATUS[status].label}</span>;
}

export function AccessClasses({ access }: { access: ToolAccess[] }) {
  return (
    <span className="flex flex-wrap gap-1">
      {access.map((a) => (
        <AccessBadge key={a} access={a} />
      ))}
    </span>
  );
}

/** "in 6 days", "3 days ago", coloured by how soon. */
export function ExpiryText({ at, className }: { at?: string; className?: string }) {
  if (!at) return <span className={cn('text-xs text-muted-foreground', className)}>No expiry</span>;
  const days = Math.round((new Date(at).getTime() - Date.now()) / 86_400_000);
  const label = days < 0 ? `Expired ${Math.abs(days)} ${Math.abs(days) === 1 ? 'day' : 'days'} ago` : days === 0 ? 'Expires today' : `Expires in ${days} ${days === 1 ? 'day' : 'days'}`;
  return (
    <span
      title={new Date(at).toLocaleDateString('en-CA', { dateStyle: 'medium' })}
      className={cn('text-xs whitespace-nowrap tabular-nums', days < 0 ? 'font-medium text-destructive' : days <= 7 ? 'font-medium text-warning-text' : days <= 30 ? 'text-warning-text' : 'text-muted-foreground', className)}
    >
      {label}
    </span>
  );
}

export const BINDING_LABEL: Record<BindingSource, string> = {
  'case.account': 'Case account',
  'case.customerId': 'Case customer',
  'case.id': 'Case',
  'case.requesterEmail': 'Requester email',
  'case.queue': 'Case queue',
};

/** "accountId ← case.account · model may narrow only" */
export function BindingText({ binding }: { binding: SubjectBinding | null }) {
  if (!binding) return <span className="text-xs text-muted-foreground">No record</span>;
  return (
    <span className="text-xs whitespace-nowrap">
      <code className="font-mono">{binding.arg}</code> ← {BINDING_LABEL[binding.bindTo].toLowerCase()}
      <span className="text-muted-foreground">{binding.mode === 'equals' ? ' · fixed' : ' · may narrow'}</span>
    </span>
  );
}

export const CREDENTIAL_KIND: Record<CredentialKind | 'none', string> = {
  oauth_client_credentials: 'OAuth client credentials',
  mtls: 'Mutual TLS',
  api_key: 'API key',
  basic: 'Basic auth',
  none: 'No credential',
};

export const ENV_LABEL: Record<Environment, string> = { dev: 'Dev', test: 'Test', production: 'Production' };

export const errorTone = (rate: number) => (rate >= 0.02 ? 'font-medium text-destructive' : 'text-muted-foreground');
export const pctText = (rate: number) => `${(rate * 100).toFixed(1)}%`;
