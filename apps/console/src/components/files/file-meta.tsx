import { CheckCircle2, File, FileArchive, FileImage, FileSpreadsheet, FileText, Loader2, Lock, Scale, ShieldAlert, ShieldX } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { FilePurpose, FileRecord, FileReferenceType, FileScan, FileSensitivity, ScanStatus, StorageBackendName, StorageCredentialKind } from '@/lib/types/files';
import { cn } from '@/lib/utils';

export { PURPOSE_LABEL } from '@/lib/file-purposes';

/** A storage credential's kind as the Storage and Secrets pages name it. */
export const CREDENTIAL_KIND_LABEL: Record<StorageCredentialKind, string> = { aws_access_key: 'AWS access key', azure_service_principal: 'Azure service principal' };
/** A storage backend as the Storage page and a file's storage section name it. */
export const BACKEND_LABEL: Record<StorageBackendName, string> = { local: 'Local disk', s3: 'Amazon S3 or S3-compatible', azure_blob: 'Azure Blob Storage' };
export const SENSITIVITY_LABEL: Record<FileSensitivity, string> = { public: 'Public', internal: 'Internal', confidential: 'Confidential', restricted: 'Restricted' };
export const SCAN_LABEL: Record<ScanStatus, string> = { pending: 'Scanning', clean: 'Clean', infected: 'Infected', failed: 'Scan failed' };
/** The Scan row of a file's details: the engine, when it ran and what it found, or "Not scanned" when scanning is off. */
export function scanSummary(scan: FileScan, relative: (iso: string) => string): string {
  // files-service records engine "off" and the mock "Scanning off" for a file that no scanner read.
  if (/^(scanning )?off$/i.test(scan.engine ?? '')) return 'Not scanned';
  return `${scan.engine ?? '—'}${scan.at ? ` · ${relative(scan.at)}` : ''}${scan.detail ? ` · ${scan.detail}` : ''}`;
}
/** What the deployment's scanning mode means for an upload; the mode is files-service's `off`, `inline` or `hook`. */
export function scanningText(mode: string): string {
  if (mode === 'off') return 'Files are not scanned.';
  if (mode === 'inline') return 'Files are scanned as they upload.';
  if (mode === 'hook') return 'Files are scanned by the deployment’s scanner after they upload.';
  return 'Scanning is set by the deployment.';
}
export const REF_LABEL: Record<FileReferenceType, string> = { source: 'Source', case: 'Case', chat: 'Chat', eval_set: 'Eval set', test_set: 'Test set', evidence: 'Evidence', export: 'Export', tool_module: 'Tool module', skill: 'Skill' };

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
  clean: { icon: CheckCircle2, cls: 'text-success-text' },
  infected: { icon: ShieldX, cls: 'text-destructive' },
  failed: { icon: ShieldAlert, cls: 'text-warning-text' },
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
  confidential: 'border-warning/40 bg-warning/10 text-warning-text',
  restricted: 'border-destructive/40 bg-destructive/10 text-destructive',
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
