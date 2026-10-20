import Link from 'next/link';
import { Archive, Banknote, BookOpen, Building2, Cloud, CloudCog, FolderKanban, Gauge, Github, HardDrive, Headset, Landmark, LifeBuoy, Mail, Plug, Server, StickyNote } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import type { AuthMethod, ConnectionRef, IntegrationKind, IntegrationStatus, Tone } from '@/lib/types/integrations';
import { cn } from '@/lib/utils';

const pill = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap';

export const KIND: Record<IntegrationKind, { label: string; icon: LucideIcon; tint: string }> = {
  m365: { label: 'Microsoft 365', icon: Mail, tint: 'bg-sky-500/10 text-sky-700 dark:text-sky-300' },
  sharepoint: { label: 'SharePoint', icon: Cloud, tint: 'bg-teal-500/10 text-teal-700 dark:text-teal-300' },
  confluence: { label: 'Confluence', icon: BookOpen, tint: 'bg-blue-500/10 text-blue-700 dark:text-blue-300' },
  salesforce: { label: 'Salesforce', icon: Building2, tint: 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300' },
  core_banking: { label: 'Core banking', icon: Landmark, tint: 'bg-success/10 text-success-text' },
  case_management: { label: 'Case management system', icon: FolderKanban, tint: 'bg-violet-500/10 text-violet-700 dark:text-violet-300' },
  servicenow: { label: 'ServiceNow', icon: Headset, tint: 'bg-lime-500/10 text-lime-700 dark:text-lime-300' },
  payments_hub: { label: 'Payments hub', icon: Banknote, tint: 'bg-warning/10 text-warning-text' },
  internal_mcp: { label: 'Internal MCP server', icon: Plug, tint: 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300' },
  gdrive: { label: 'Google Drive', icon: HardDrive, tint: 'bg-warning/10 text-warning-text' },
  zendesk: { label: 'Zendesk', icon: LifeBuoy, tint: 'bg-success/10 text-success-text' },
  github: { label: 'GitHub', icon: Github, tint: 'bg-muted text-foreground' },
  notion: { label: 'Notion', icon: StickyNote, tint: 'bg-stone-500/10 text-stone-700 dark:text-stone-300' },
  credit_bureau: { label: 'Credit bureau', icon: Gauge, tint: 'bg-destructive/10 text-destructive' },
  internal_api: { label: 'Internal API', icon: Server, tint: 'bg-muted text-foreground' },
  aws_s3: { label: 'Amazon S3', icon: Archive, tint: 'bg-orange-500/10 text-orange-700 dark:text-orange-300' },
  azure_blob: { label: 'Azure Blob Storage', icon: CloudCog, tint: 'bg-sky-500/10 text-sky-700 dark:text-sky-300' },
};

/** A kind's label, glyph and tile. A kind the console does not know yet (a new connector) reads as its name on a plain
 * tile instead of breaking every page that draws it. */
export function kindOf(kind: string): { label: string; icon: LucideIcon; tint: string } {
  return (KIND as Record<string, { label: string; icon: LucideIcon; tint: string } | undefined>)[kind] ?? { label: kind.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase()), icon: Plug, tint: 'bg-muted text-muted-foreground' };
}

export const AUTH: Record<AuthMethod, { label: string; hint: string }> = {
  oauth_consent: { label: 'OAuth consent', hint: 'An admin signs in and grants the scopes. Consent expires and is renewed by signing in again.' },
  service_principal: { label: 'Service principal', hint: 'An app registration whose client secret or certificate sits in the bank vault.' },
  api_key: { label: 'API key', hint: 'A key issued by the system, stored in the bank vault.' },
  mtls: { label: 'Mutual TLS', hint: 'A client certificate in the bank vault, presented on every call.' },
};

const STATUS: Record<IntegrationStatus, { label: string; cls: string; dot: string }> = {
  draft: { label: 'Draft', cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
  healthy: { label: 'Healthy', cls: 'border-success/40 bg-success/10 text-success-text', dot: 'bg-success' },
  expiring: { label: 'Expiring', cls: 'border-warning/40 bg-warning/10 text-warning-text', dot: 'bg-warning' },
  needs_reconnect: { label: 'Needs reconnect', cls: 'border-destructive/40 bg-destructive/10 text-destructive', dot: 'bg-destructive' },
  error: { label: 'Error', cls: 'border-destructive/40 bg-destructive/10 text-destructive', dot: 'bg-destructive' },
  revoked: { label: 'Revoked', cls: 'border-border bg-muted text-muted-foreground', dot: 'bg-muted-foreground' },
};
export const STATUS_LABEL = Object.fromEntries(Object.entries(STATUS).map(([k, v]) => [k, v.label])) as Record<IntegrationStatus, string>;

export function IntegrationStatusBadge({ status }: { status: IntegrationStatus }) {
  const s = STATUS[status];
  return (
    <span className={cn(pill, s.cls)}>
      <span className={cn('size-1.5 rounded-full', s.dot)} />
      {s.label}
    </span>
  );
}

export const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-success-text',
  warn: 'text-warning-text',
  bad: 'font-medium text-destructive',
  muted: 'text-muted-foreground',
};

/** The system's mark: its kind's glyph on a tinted tile. */
export function SystemMark({ kind, className, size = 'md' }: { kind: IntegrationKind; className?: string; size?: 'sm' | 'md' | 'lg' }) {
  const k = kindOf(kind);
  return (
    <span className={cn('flex shrink-0 items-center justify-center rounded-md', k.tint, size === 'sm' ? 'size-5' : size === 'lg' ? 'size-10' : 'size-8', className)} aria-hidden>
      <k.icon className={size === 'sm' ? 'size-3' : size === 'lg' ? 'size-5' : 'size-4'} />
    </span>
  );
}

/** Read-only link to the integration a source, module or mailbox uses, with its status. */
export function ConnectionChip({ connection, className }: { connection: ConnectionRef | null | undefined; className?: string }) {
  if (!connection) return <span className={cn('text-xs text-muted-foreground', className)}>Built in, no connection</span>;
  const s = STATUS[connection.status];
  return (
    <Link
      href={`/integrations/${connection.id}`}
      className={cn('inline-flex max-w-full items-center gap-1.5 rounded-md border bg-card py-0.5 pr-2 pl-0.5 text-xs hover:bg-muted', className)}
      title={`${connection.name} · ${s.label}. Managed in Integrations.`}
      data-testid="connection-chip"
    >
      <SystemMark kind={connection.kind} size="sm" />
      <span className="truncate font-medium">{connection.name}</span>
      <span className={cn('size-1.5 shrink-0 rounded-full', s.dot)} />
      <span className="shrink-0 text-muted-foreground">{s.label}</span>
    </Link>
  );
}
