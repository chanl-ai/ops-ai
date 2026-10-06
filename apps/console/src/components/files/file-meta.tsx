import { CheckCircle2, File, FileArchive, FileImage, FileSpreadsheet, FileText, Loader2, Lock, Scale, ShieldAlert, ShieldX } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { FilePurpose, FileRecord, FileReferenceType, FileSensitivity, ScanStatus } from '@/lib/types/files';
import { cn } from '@/lib/utils';

export const PURPOSE_LABEL: Record<FilePurpose, string> = {
  knowledge_source: 'Knowledge source',
  chat_attachment: 'Chat attachment',
  case_attachment: 'Email attachment',
  test_import: 'Test import',
  evidence_bundle: 'Evidence bundle',
  export: 'Export',
  tool_spec: 'Tool spec',
  avatar: 'Logo or avatar',
};

export const SENSITIVITY_LABEL: Record<FileSensitivity, string> = { public: 'Public', internal: 'Internal', confidential: 'Confidential', restricted: 'Restricted' };
export const SCAN_LABEL: Record<ScanStatus, string> = { pending: 'Scanning', clean: 'Clean', infected: 'Infected', failed: 'Scan failed' };
export const REF_LABEL: Record<FileReferenceType, string> = { source: 'Source', case: 'Case', chat: 'Chat', eval_set: 'Eval set', test_set: 'Test set', evidence: 'Evidence', export: 'Export', tool_module: 'Tool module' };

export function fileIcon(name: string): LucideIcon {
  const e = name.split('.').pop()?.toLowerCase() ?? '';
  if (['csv', 'xlsx', 'xlsm'].includes(e)) return FileSpreadsheet;
  if (['png', 'jpg', 'jpeg', 'svg'].includes(e)) return FileImage;
  if (['zip'].includes(e)) return FileArchive;
  if (['pdf', 'docx', 'docm', 'txt', 'md', 'html', 'eml', 'yaml', 'yml', 'json'].includes(e)) return FileText;
  return File;
}

const SCAN_TONE: Record<ScanStatus, { icon: LucideIcon; cls: string }> = {
  pending: { icon: Loader2, cls: 'text-muted-foreground' },
  clean: { icon: CheckCircle2, cls: 'text-emerald-700 dark:text-emerald-400' },
  infected: { icon: ShieldX, cls: 'text-red-600 dark:text-red-400' },
  failed: { icon: ShieldAlert, cls: 'text-amber-700 dark:text-amber-400' },
};

export function ScanText({ status, detail }: { status: ScanStatus; detail?: string }) {
  const t = SCAN_TONE[status];
  return (
    <span className={cn('inline-flex items-center gap-1 text-xs font-medium whitespace-nowrap', t.cls)} title={detail}>
      <t.icon className={cn('size-3.5', status === 'pending' && 'animate-spin')} /> {SCAN_LABEL[status]}
    </span>
  );
}

const SENS_TONE: Record<FileSensitivity, string> = {
  public: '',
  internal: '',
  confidential: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300',
  restricted: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300',
};

export function SensitivityBadge({ value, suggested }: { value: FileSensitivity; suggested?: boolean }) {
  const badge = (
    <Badge variant="outline" className={cn('font-normal', SENS_TONE[value])}>
      {SENSITIVITY_LABEL[value]}
      {suggested && <span className="text-muted-foreground">· suggested</span>}
    </Badge>
  );
  if (!suggested) return badge;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent className="max-w-xs">Suggested from what the file is for. Nobody has confirmed it yet.</TooltipContent>
    </Tooltip>
  );
}

/** Retention class, delete-after date, and the hold or WORM lock that overrides it. */
export function RetentionCell({ file }: { file: Pick<FileRecord, 'retention' | 'legalHold' | 'immutable'> }) {
  return (
    <div className="flex w-48 flex-col gap-0.5">
      <span className="truncate text-sm" title={file.retention.className}>
        {file.retention.className}
      </span>
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {file.legalHold ? (
          <span className="inline-flex items-center gap-1 font-medium text-violet-700 dark:text-violet-300" title={file.legalHold.reason}>
            <Scale className="size-3" /> Legal hold
          </span>
        ) : file.retention.deleteAfter ? (
          `Delete after ${file.retention.deleteAfter}`
        ) : (
          'Kept until deleted'
        )}
        {file.immutable && (
          <span className="inline-flex items-center gap-0.5" title="WORM: cannot be changed or deleted before retention ends">
            <Lock className="size-3" /> WORM
          </span>
        )}
      </span>
    </div>
  );
}
