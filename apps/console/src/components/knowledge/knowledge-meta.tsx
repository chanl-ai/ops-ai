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
  PenLine,
  Presentation,
  Puzzle,
  Send,
  Shield,
  ShieldAlert,
  ShieldCheck,
  StickyNote,
  Type,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import type { ErrorClass, Item, ItemStatus, KbHealth, RunStatus, RunTrigger, Schedule, Sensitivity, SourceHealth, SourceKind, SourceStatus, SourceType, Weekday } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

type Tone = 'good' | 'warn' | 'bad' | 'neutral' | 'info';

const toneClass: Record<Tone, string> = {
  good: 'border-success/40 bg-success/10 text-success-text',
  warn: 'border-warning/40 bg-warning/10 text-warning-text',
  bad: 'border-destructive/40 bg-destructive/10 text-destructive-text',
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
  running: ['info', Loader2, 'Running'],
  success: ['good', CheckCircle2, 'Done'],
  partial: ['warn', AlertTriangle, 'Done with failures'],
  failed: ['bad', XCircle, 'Failed'],
  cancelled: ['neutral', MinusCircle, 'Cancelled'],
  skipped: ['neutral', MinusCircle, 'Skipped'],
};
export const RUN_LABEL = Object.fromEntries(Object.entries(RUN).map(([k, v]) => [k, v[2]])) as Record<RunStatus, string>;
export function RunStatusBadge({ status }: { status?: RunStatus }) {
  if (!status) return <StatusBadge tone="neutral" icon={CircleDashed} label="Never synced" />;
  const [tone, icon, label] = RUN[status] ?? ['neutral', CircleDashed, status];
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

export function FreshnessBadge({ reviewBy, freshness }: { reviewBy: string; freshness?: 'fresh' | 'stale' | 'no_schedule' }) {
  // The service decides: stale when the source missed its schedule, and no schedule means nothing to be fresh against.
  if (freshness === 'no_schedule') return <StatusBadge tone="neutral" icon={Clock} label="No schedule" />;
  if (freshness === 'stale') return <StatusBadge tone="warn" icon={AlertTriangle} label="Stale" />;
  if (freshness === 'fresh') return <StatusBadge tone="good" icon={CheckCircle2} label="Fresh" />;
  const days = Math.round((new Date(reviewBy).getTime() - Date.now()) / 86400_000);
  if (days < 0) return <StatusBadge tone="warn" icon={AlertTriangle} label={`Stale · ${-days} d`} />;
  if (days < 14) return <StatusBadge tone="warn" icon={Clock} label={`Review in ${days} d`} />;
  return <StatusBadge tone="good" icon={CheckCircle2} label="Fresh" />;
}

export function MimeIcon({ mime, className }: { mime: string; className?: string }) {
  const c = cn('size-4 shrink-0 text-muted-foreground', className);
  if (mime === 'application/pdf') return <FileText className={cn(c, 'text-destructive-text')} />;
  if (mime.includes('spreadsheet') || mime === 'text/csv') return <FileSpreadsheet className={cn(c, 'text-success-text')} />;
  if (mime.includes('presentation')) return <Presentation className={cn(c, 'text-orange-500')} />;
  if (mime.includes('wordprocessing')) return <FileText className={cn(c, 'text-blue-500')} />;
  if (mime === 'text/markdown' || mime === 'text/plain') return <FileCode2 className={c} />;
  if (mime === 'text/html') return <Globe className={c} />;
  return <File className={c} />;
}

export const KB_COLORS: Record<string, string> = {
  violet: 'bg-violet-500',
  blue: 'bg-blue-500',
  emerald: 'bg-success',
  amber: 'bg-warning',
  rose: 'bg-destructive',
  slate: 'bg-muted-foreground',
  teal: 'bg-teal-500',
};

export function KbDot({ color, className }: { color: string; className?: string }) {
  return <span className={cn('inline-block size-2.5 shrink-0 rounded-full', KB_COLORS[color] ?? 'bg-muted-foreground', className)} />;
}

const KIND_ICON: Record<SourceKind, LucideIcon> = { file: FileUp, text: PenLine, push: Send, web: Globe, tool: Puzzle };

/** The icon for what a source is: files, a website, or an app's knowledge source. The console keeps only icons by kind. */
export function SourceKindIcon({ kind, className }: { kind: SourceKind; className?: string }) {
  const Icon = KIND_ICON[kind] ?? Puzzle;
  return <Icon className={className ?? 'size-4 shrink-0 text-muted-foreground'} />;
}

/** A source's health as kb-service reports it, in one cell: healthy, failing with its days and runs, or needs reconnect. */
export function SourceHealthText({ health }: { health?: SourceHealth }) {
  const h = health ?? { state: 'never' as const, daysFailing: 0, failedRuns: 0, tombstoned: 0 };
  const removed = h.tombstoned ? ` · ${h.tombstoned} removed` : '';
  if (h.state === 'failing')
    return (
      <span className="inline-flex items-center gap-1 text-sm whitespace-nowrap text-destructive-text">
        <XCircle className="size-3.5" /> Failing {h.daysFailing === 1 ? '1 day' : `${h.daysFailing} days`} · {h.failedRuns === 1 ? '1 run' : `${h.failedRuns} runs`} in a row{removed}
      </span>
    );
  if (h.state === 'needs_reconnect')
    return (
      <span className="inline-flex items-center gap-1 text-sm whitespace-nowrap text-warning-text">
        <AlertTriangle className="size-3.5" /> Needs reconnect{removed}
      </span>
    );
  if (h.state === 'never')
    return (
      <span className="inline-flex items-center gap-1 text-sm whitespace-nowrap text-muted-foreground">
        <CircleDashed className="size-3.5" /> Never synced
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-sm whitespace-nowrap text-success-text">
      <CheckCircle2 className="size-3.5" /> Healthy{removed}
    </span>
  );
}

export const WEEKDAY_LABEL: Record<Weekday, string> = { mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday' };

export function scheduleLabel(s: Schedule) {
  switch (s.kind) {
    case 'manual':
      return 'Manual';
    case 'hourly':
      return s.every === 1 ? 'Every hour' : `Every ${s.every} h`;
    case 'daily':
      return `Daily ${s.time}`;
    case 'weekly':
      return `Weekly ${WEEKDAY_LABEL[s.day]?.slice(0, 3) ?? s.day} ${s.time}`;
  }
}

export const SCHEDULE_KIND_LABEL: Record<Schedule['kind'], string> = { manual: 'Manual', hourly: 'Every few hours', daily: 'Daily', weekly: 'Weekly' };

export const TRIGGER_LABEL: Record<RunTrigger, string> = { manual: 'Sync now', schedule: 'Schedule', full: 'Full resync', retry: 'Retry failed', settings: 'Settings changed' };
export const triggerLabel = (t: string) => TRIGGER_LABEL[t as RunTrigger] ?? t;

export const ERROR_CLASS_LABEL: Record<ErrorClass, string> = { parse: 'Parse', fetch: 'Fetch', permission: 'Permission', too_large: 'Too large', rate_limited: 'Rate limited' };

/** The step of a run an error happened at. */
const STEP_LABEL: Record<string, string> = { list: 'List', get: 'Fetch', store: 'Store', parse: 'Read' };
export const stepLabel = (step: string) => STEP_LABEL[step] ?? step;

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
