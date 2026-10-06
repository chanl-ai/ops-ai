import {
  AlertTriangle,
  BookOpen,
  Building2,
  CheckCircle2,
  CircleDashed,
  Clock,
  Cloud,
  File,
  FileCode2,
  FileSpreadsheet,
  FileText,
  FileUp,
  Github,
  Globe,
  HardDrive,
  LifeBuoy,
  Link2,
  Loader2,
  MinusCircle,
  PauseCircle,
  Presentation,
  Shield,
  ShieldAlert,
  ShieldCheck,
  StickyNote,
  Type,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { ErrorClass, Item, ItemStatus, KbHealth, RunPhase, RunStatus, Schedule, Sensitivity, SourceStatus, SourceType, SyncRun } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

type Tone = 'good' | 'warn' | 'bad' | 'neutral' | 'info';

const toneClass: Record<Tone, string> = {
  good: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300',
  warn: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-300',
  bad: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300',
  neutral: 'border-border bg-muted text-muted-foreground',
  info: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/50 dark:text-blue-300',
};

/** Status always carries an icon and a label as well as a hue. */
function StatusBadge({ tone, icon: Icon, label, spin }: { tone: Tone; icon: LucideIcon; label: string; spin?: boolean }) {
  return (
    <Badge variant="outline" className={cn('gap-1 whitespace-nowrap font-medium', toneClass[tone])}>
      <Icon className={cn('size-3', spin && 'animate-spin')} />
      {label}
    </Badge>
  );
}

const HEALTH: Record<KbHealth, [Tone, LucideIcon, string]> = {
  healthy: ['good', CheckCircle2, 'Healthy'],
  indexing: ['info', Loader2, 'Indexing'],
  degraded: ['warn', AlertTriangle, 'Degraded'],
  failed: ['bad', XCircle, 'Failed'],
  never: ['neutral', CircleDashed, 'Never indexed'],
};
export const HEALTH_LABEL = Object.fromEntries(Object.entries(HEALTH).map(([k, v]) => [k, v[2]])) as Record<KbHealth, string>;
export function KbHealthBadge({ health }: { health: KbHealth }) {
  const [tone, icon, label] = HEALTH[health];
  return <StatusBadge tone={tone} icon={icon} label={label} spin={health === 'indexing'} />;
}

const RUN: Record<RunStatus, [Tone, LucideIcon, string]> = {
  success: ['good', CheckCircle2, 'Success'],
  partial: ['warn', AlertTriangle, 'Partial'],
  failed: ['bad', XCircle, 'Failed'],
  running: ['info', Loader2, 'Running'],
  backing_off: ['warn', Clock, 'Backing off'],
};
export const RUN_LABEL = Object.fromEntries(Object.entries(RUN).map(([k, v]) => [k, v[2]])) as Record<RunStatus, string>;
export function RunStatusBadge({ status }: { status?: RunStatus }) {
  if (!status) return <StatusBadge tone="neutral" icon={CircleDashed} label="Never synced" />;
  const [tone, icon, label] = RUN[status];
  return <StatusBadge tone={tone} icon={icon} label={label} spin={status === 'running'} />;
}

const SOURCE_STATUS: Record<SourceStatus, [Tone, LucideIcon, string]> = {
  active: ['good', CheckCircle2, 'Active'],
  paused: ['neutral', PauseCircle, 'Paused'],
  draft: ['neutral', CircleDashed, 'Draft'],
  revoked: ['bad', ShieldAlert, 'Connection revoked'],
};
export const SOURCE_STATUS_LABEL = Object.fromEntries(Object.entries(SOURCE_STATUS).map(([k, v]) => [k, v[2]])) as Record<SourceStatus, string>;
export function SourceStatusBadge({ status }: { status: SourceStatus }) {
  const [tone, icon, label] = SOURCE_STATUS[status];
  return <StatusBadge tone={tone} icon={icon} label={label} />;
}

const ITEM: Record<ItemStatus, [Tone, LucideIcon, string]> = {
  indexed: ['good', CheckCircle2, 'Indexed'],
  pending: ['neutral', Clock, 'Pending'],
  processing: ['info', Loader2, 'Processing'],
  failed: ['bad', XCircle, 'Failed'],
  partial: ['warn', AlertTriangle, 'Partial'],
  excluded: ['neutral', MinusCircle, 'Excluded'],
  deleted: ['neutral', MinusCircle, 'Deleted at source'],
  held: ['warn', PauseCircle, 'Held'],
};
export const ITEM_STATUS_LABEL = Object.fromEntries(Object.entries(ITEM).map(([k, v]) => [k, v[2]])) as Record<ItemStatus, string>;
export function ItemStatusBadge({ status }: { status: ItemStatus }) {
  const [tone, icon, label] = ITEM[status];
  return <StatusBadge tone={tone} icon={icon} label={label} spin={status === 'processing'} />;
}

const SENSITIVITY: Record<Sensitivity, [Tone, LucideIcon, string]> = {
  internal: ['neutral', Shield, 'Internal'],
  confidential: ['warn', ShieldCheck, 'Confidential'],
  restricted: ['bad', ShieldAlert, 'Restricted'],
};
export const SENSITIVITY_LABEL = Object.fromEntries(Object.entries(SENSITIVITY).map(([k, v]) => [k, v[2]])) as Record<Sensitivity, string>;
export function SensitivityBadge({ level }: { level: Sensitivity }) {
  const [tone, icon, label] = SENSITIVITY[level];
  return <StatusBadge tone={tone} icon={icon} label={label} />;
}

export function FreshnessBadge({ reviewBy }: { reviewBy: string }) {
  const days = Math.round((new Date(reviewBy).getTime() - Date.now()) / 86400_000);
  if (days < 0) return <StatusBadge tone="warn" icon={AlertTriangle} label={`Stale · ${-days} d`} />;
  if (days < 14) return <StatusBadge tone="warn" icon={Clock} label={`Review in ${days} d`} />;
  return <StatusBadge tone="good" icon={CheckCircle2} label="Fresh" />;
}

export function MimeIcon({ mime, className }: { mime: string; className?: string }) {
  const c = cn('size-4 shrink-0 text-muted-foreground', className);
  if (mime === 'application/pdf') return <FileText className={cn(c, 'text-red-500')} />;
  if (mime.includes('spreadsheet') || mime === 'text/csv') return <FileSpreadsheet className={cn(c, 'text-emerald-600')} />;
  if (mime.includes('presentation')) return <Presentation className={cn(c, 'text-orange-500')} />;
  if (mime.includes('wordprocessing')) return <FileText className={cn(c, 'text-blue-500')} />;
  if (mime === 'text/markdown' || mime === 'text/plain') return <FileCode2 className={c} />;
  if (mime === 'text/html') return <Globe className={c} />;
  return <File className={c} />;
}

export const KB_COLORS: Record<string, string> = {
  violet: 'bg-violet-500',
  blue: 'bg-blue-500',
  emerald: 'bg-emerald-500',
  amber: 'bg-amber-500',
  rose: 'bg-rose-500',
  slate: 'bg-slate-500',
  teal: 'bg-teal-500',
};

export function KbDot({ color, className }: { color: string; className?: string }) {
  return <span className={cn('inline-block size-2.5 shrink-0 rounded-full', KB_COLORS[color] ?? 'bg-slate-400', className)} />;
}

export interface SourceTypeMeta {
  type: SourceType;
  label: string;
  short: string;
  description: string;
  group: 'Content you provide' | 'Connected apps';
  icon: LucideIcon;
  connected: boolean;
  supportsInherit: boolean;
  supportsWebhook: boolean;
  changeDetection: string;
  scopeLabel: string;
}

export const SOURCE_TYPES: SourceTypeMeta[] = [
  { type: 'file', label: 'File upload', short: 'Files', description: 'PDF, DOCX, XLSX, PPTX, CSV, TXT, MD, HTML. 50 MB each.', group: 'Content you provide', icon: FileUp, connected: false, supportsInherit: false, supportsWebhook: false, changeDetection: 'Replace or upload a new version', scopeLabel: 'Files' },
  { type: 'url', label: 'Single URL', short: 'URL', description: 'One or more page URLs, one per line. Optional header auth for intranets.', group: 'Content you provide', icon: Link2, connected: false, supportsInherit: false, supportsWebhook: false, changeDetection: 'ETag, then content hash', scopeLabel: 'URLs' },
  { type: 'crawl', label: 'Website crawl or sitemap', short: 'Crawl', description: 'Start URL or sitemap, depth, page limit, path patterns, robots respected.', group: 'Content you provide', icon: Globe, connected: false, supportsInherit: false, supportsWebhook: false, changeDetection: 'Sitemap lastmod, ETag, content hash', scopeLabel: 'Start URL' },
  { type: 'text', label: 'Plain text or table', short: 'Text', description: 'Paste Markdown, or a CSV where each row becomes a chunk and headers become fields.', group: 'Content you provide', icon: Type, connected: false, supportsInherit: false, supportsWebhook: false, changeDetection: 'Edit in place creates a revision', scopeLabel: 'Content' },
  { type: 'sharepoint', label: 'SharePoint / OneDrive', short: 'SharePoint', description: 'Sites, then libraries or folders. Office and PDF. App-only or delegated auth.', group: 'Connected apps', icon: Cloud, connected: true, supportsInherit: true, supportsWebhook: true, changeDetection: 'Drive delta queries; webhook subscriptions', scopeLabel: 'Site and libraries' },
  { type: 'confluence', label: 'Confluence', short: 'Confluence', description: 'Site, spaces, optional parent page, attachments.', group: 'Connected apps', icon: BookOpen, connected: true, supportsInherit: true, supportsWebhook: false, changeDetection: 'Last-modified since cursor', scopeLabel: 'Spaces' },
  { type: 'gdrive', label: 'Google Drive', short: 'Drive', description: 'Shared drives and folders. Docs, Sheets and Slides exported.', group: 'Connected apps', icon: HardDrive, connected: true, supportsInherit: true, supportsWebhook: true, changeDetection: 'Changes feed with page token', scopeLabel: 'Drives and folders' },
  { type: 'github', label: 'GitHub', short: 'GitHub', description: 'Installation, repos, branch and path globs.', group: 'Connected apps', icon: Github, connected: true, supportsInherit: true, supportsWebhook: true, changeDetection: 'Head commit compare; push webhooks', scopeLabel: 'Repos and paths' },
  { type: 'notion', label: 'Notion', short: 'Notion', description: 'Pages and databases, with child pages.', group: 'Connected apps', icon: StickyNote, connected: true, supportsInherit: false, supportsWebhook: false, changeDetection: 'Last-edited since cursor', scopeLabel: 'Pages' },
  { type: 'zendesk', label: 'Zendesk', short: 'Zendesk', description: 'Help centre categories and sections, locales, published only.', group: 'Connected apps', icon: LifeBuoy, connected: true, supportsInherit: false, supportsWebhook: false, changeDetection: 'Incremental articles API', scopeLabel: 'Categories' },
  { type: 'salesforce', label: 'Salesforce Knowledge', short: 'Salesforce', description: 'Org, article types, data categories, language, published channel.', group: 'Connected apps', icon: Building2, connected: true, supportsInherit: false, supportsWebhook: false, changeDetection: 'LastModifiedDate since cursor', scopeLabel: 'Article types' },
];

export const sourceTypeMeta = (type: SourceType) => SOURCE_TYPES.find((t) => t.type === type)!;

export function SourceTypeIcon({ type, className }: { type: SourceType; className?: string }) {
  const Icon = sourceTypeMeta(type).icon;
  return <Icon className={className ?? 'size-4 shrink-0 text-muted-foreground'} />;
}

export function scheduleLabel(s: Schedule) {
  switch (s.kind) {
    case 'manual':
      return 'Manual';
    case 'daily':
      return `Daily ${s.time}`;
    case 'weekly':
      return `Weekly ${s.day} ${s.time}`;
    case 'monthly':
      return `Monthly on day ${s.day} at ${s.time}`;
    case 'webhook':
      return s.safetyNetDaily ? 'Webhook + daily' : 'Webhook';
  }
}

export const SCHEDULE_KIND_LABEL: Record<Schedule['kind'], string> = { manual: 'Manual', daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly', webhook: 'Webhook' };

export const TRIGGER_LABEL: Record<SyncRun['trigger'], string> = { manual: 'Manual', schedule: 'Schedule', webhook: 'Webhook', full: 'Full resync', retry: 'Retry failed' };

export const ERROR_CLASS_LABEL: Record<ErrorClass, string> = { parse: 'Parse', fetch: 'Fetch', permission: 'Permission', too_large: 'Too large', rate_limited: 'Rate limited' };

export const PHASE_LABEL: Record<RunPhase['name'], string> = { list: 'List changes', fetch: 'Fetch', parse: 'Parse', chunk: 'Chunk', embed: 'Embed', upsert: 'Upsert' };

export function PhaseIcon({ status }: { status: RunPhase['status'] }) {
  if (status === 'done') return <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-400" aria-label="Done" />;
  if (status === 'running') return <Loader2 className="size-4 animate-spin text-blue-600 dark:text-blue-400" aria-label="Running" />;
  if (status === 'failed') return <XCircle className="size-4 text-destructive" aria-label="Failed" />;
  return <CircleDashed className="size-4 text-muted-foreground" aria-label="Not run" />;
}

export const phaseStatusLabel = (s: RunPhase['status']) => (s === 'done' ? 'Done' : s === 'running' ? 'Running' : s === 'failed' ? 'Failed' : 'Not run');

/** When a backing-off run retries, from the Retry-After in its error, or 15 minutes. */
export function backoffRetryAt(run: SyncRun) {
  const m = run.errors.map((e) => e.message.match(/Retry-After (\d+)s/)).find(Boolean);
  const wait = m ? Number(m[1]) : 900;
  return new Date(new Date(run.startedAt).getTime() + (run.durationSec + wait) * 1000).toISOString();
}

export const RULE_FIELDS = [
  { value: 'path', label: 'Path glob' },
  { value: 'title', label: 'Title contains' },
  { value: 'mime', label: 'MIME type' },
  { value: 'modifiedAfter', label: 'Modified after' },
  { value: 'sizeUnder', label: 'Size under' },
] as const;

/** Each rule field's value example, so the placeholder follows the field. */
export const RULE_PLACEHOLDER: Record<(typeof RULE_FIELDS)[number]['value'], string> = {
  path: 'e.g. **/Archive/**',
  title: 'e.g. draft',
  mime: 'e.g. application/zip',
  modifiedAfter: 'e.g. 2026-01-01',
  sizeUnder: 'e.g. 50 MB',
};

export const PARSING_OPTIONS = [
  { k: 'ocr' as const, label: 'OCR', tip: 'Runs on scanned PDFs and images. Slower and uses credits.' },
  { k: 'tables' as const, label: 'Keep tables', tip: 'Tables in PDF, DOCX and XLSX keep their columns, so table rows and structured values can read them.' },
  { k: 'vision' as const, label: 'Vision for figures', tip: 'Describes images and charts into text.' },
];

export const RETRIEVAL_PRESETS = {
  balanced: { searchMode: 'hybrid', rerank: true, chunkLimit: 8, threshold: 0.5, answerShape: 'answer_with_citations', temperature: 0.1 },
  precise: { searchMode: 'hybrid', rerank: true, chunkLimit: 5, threshold: 0.65, answerShape: 'answer_with_citations', temperature: 0 },
  raw: { searchMode: 'hybrid', rerank: false, chunkLimit: 10, threshold: 0.4, answerShape: 'chunks' },
} as const;

/** Why an item is not searched as-is: the rule, the missing metadata, the copy it duplicates or the version that replaced it. */
export function itemReason(i: Item): string | undefined {
  if (i.status === 'excluded') return i.excludedBy ?? 'Excluded by hand';
  if (i.status === 'held' && i.held) return `Missing ${i.held.missing.join(', ')} · required by ${i.held.kbNames.join(', ')}`;
  if (i.duplicateOf) return `Same content as ${i.duplicateOf.title} in ${i.duplicateOf.sourceName}; indexed once there`;
  if (i.versionStatus === 'superseded') return `Superseded by ${i.supersededBy}; kept for as-of questions`;
  if (i.versionStatus === 'scheduled') return `Takes effect ${i.effectiveDate}`;
  if (i.alsoIn?.length) return `Also in ${i.alsoIn.map((a) => a.sourceName).join(', ')}; indexed once`;
  return undefined;
}
