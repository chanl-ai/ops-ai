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
  core_banking: { label: 'Core banking', icon: Landmark, tint: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300' },
  case_management: { label: 'Case management system', icon: FolderKanban, tint: 'bg-violet-500/10 text-violet-700 dark:text-violet-300' },
  servicenow: { label: 'ServiceNow', icon: Headset, tint: 'bg-lime-500/10 text-lime-700 dark:text-lime-300' },
  payments_hub: { label: 'Payments hub', icon: Banknote, tint: 'bg-amber-500/10 text-amber-700 dark:text-amber-300' },
  internal_mcp: { label: 'Internal MCP server', icon: Plug, tint: 'bg-indigo-500/10 text-indigo-700 dark:text-indigo-300' },
  gdrive: { label: 'Google Drive', icon: HardDrive, tint: 'bg-yellow-500/10 text-yellow-700 dark:text-yellow-300' },
  zendesk: { label: 'Zendesk', icon: LifeBuoy, tint: 'bg-green-500/10 text-green-700 dark:text-green-300' },
  github: { label: 'GitHub', icon: Github, tint: 'bg-zinc-500/10 text-zinc-700 dark:text-zinc-300' },
  notion: { label: 'Notion', icon: StickyNote, tint: 'bg-stone-500/10 text-stone-700 dark:text-stone-300' },
  credit_bureau: { label: 'Credit bureau', icon: Gauge, tint: 'bg-rose-500/10 text-rose-700 dark:text-rose-300' },
  internal_api: { label: 'Internal API', icon: Server, tint: 'bg-slate-500/10 text-slate-700 dark:text-slate-300' },
  aws_s3: { label: 'Amazon S3', icon: Archive, tint: 'bg-orange-500/10 text-orange-700 dark:text-orange-300' },
  azure_blob: { label: 'Azure Blob Storage', icon: CloudCog, tint: 'bg-sky-500/10 text-sky-700 dark:text-sky-300' },
};

export const AUTH: Record<AuthMethod, { label: string; hint: string }> = {
  oauth_consent: { label: 'OAuth consent', hint: 'An admin signs in and grants the scopes. Consent expires and is renewed by signing in again.' },
  service_principal: { label: 'Service principal', hint: 'An app registration whose client secret or certificate sits in the bank vault.' },
  api_key: { label: 'API key', hint: 'A key issued by the system, stored in the bank vault.' },
  mtls: { label: 'Mutual TLS', hint: 'A client certificate in the bank vault, presented on every call.' },
};

const STATUS: Record<IntegrationStatus, { label: string; cls: string; dot: string }> = {
  healthy: { label: 'Healthy', cls: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300', dot: 'bg-emerald-500' },
  expiring: { label: 'Expiring', cls: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300', dot: 'bg-amber-500' },
  needs_reconnect: { label: 'Needs reconnect', cls: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300', dot: 'bg-red-500' },
  error: { label: 'Error', cls: 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300', dot: 'bg-red-500' },
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
  ok: 'text-emerald-700 dark:text-emerald-400',
  warn: 'text-amber-700 dark:text-amber-400',
  bad: 'font-medium text-red-600 dark:text-red-400',
  muted: 'text-muted-foreground',
};

/** The system's mark: its kind's glyph on a tinted tile. */
export function SystemMark({ kind, className, size = 'md' }: { kind: IntegrationKind; className?: string; size?: 'sm' | 'md' | 'lg' }) {
  const k = KIND[kind];
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
