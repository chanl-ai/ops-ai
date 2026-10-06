'use client';

import * as React from 'react';
import { AlertCircle, CheckCircle2, Copy, Loader2, Paperclip, RotateCcw, ShieldX, Upload, X } from 'lucide-react';

import { fileIcon } from '@/components/files/file-meta';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { type UploadItem, useFileUpload } from '@/hooks/file-queries';
import { bytes } from '@/lib/format';
import type { FilePurpose } from '@/lib/types/files';
import { cn } from '@/lib/utils';

export type { UploadItem } from '@/hooks/file-queries';

/** True when every item finished, passed the scan and has a file id to hand on. */
export const uploadsReady = (items: UploadItem[]) => items.length > 0 && items.every((i) => i.phase === 'ready' && !!i.fileId);
/** The message a form shows when it cannot continue yet, or undefined. */
export function uploadsBlocker(items: UploadItem[]): string | undefined {
  if (items.some((i) => i.phase === 'hashing' || i.phase === 'uploading')) return 'Wait for the upload to finish.';
  if (items.some((i) => i.phase === 'scanning')) return 'Wait for the malware scan to finish.';
  if (items.some((i) => i.phase === 'blocked')) return 'Remove the quarantined file to continue.';
  if (items.some((i) => i.phase === 'error')) return 'Remove or retry the file that failed.';
  return undefined;
}

function StatusLine({ item }: { item: UploadItem }) {
  if (item.phase === 'hashing') return <span className="text-muted-foreground">Preparing…</span>;
  if (item.phase === 'uploading') return <span className="tabular-nums text-muted-foreground">Uploading · {Math.round(item.progress * 100)}%</span>;
  if (item.phase === 'scanning')
    return (
      <span className="inline-flex items-center gap-1 text-muted-foreground">
        <Loader2 className="size-3 animate-spin" /> Scanning for malware…
      </span>
    );
  if (item.phase === 'ready')
    return (
      <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
        <CheckCircle2 className="size-3" /> {item.deduplicated ? 'Already stored in your team · reused' : 'Uploaded · scan clean'}
      </span>
    );
  if (item.phase === 'blocked')
    return (
      <span className="inline-flex items-center gap-1 text-destructive">
        <ShieldX className="size-3" /> {item.error}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-destructive">
      <AlertCircle className="size-3" /> {item.error}
    </span>
  );
}

/**
 * The one upload control in the console. Bytes go from the browser to object storage on a presigned link from
 * the Files API; callers receive file ids through `onChange` and pass those on, never the bytes. Limits come from
 * Settings → Storage. `onPick` hands over the chosen files for local preview (for example CSV rows) only.
 */
export function FileUpload({
  purpose,
  multiple = false,
  team,
  retentionClass,
  onChange,
  onPick,
  variant = 'dropzone',
  title,
  hint,
  disabled,
  id = 'file-upload',
  testId,
}: {
  purpose: FilePurpose;
  multiple?: boolean;
  team?: string;
  retentionClass?: string;
  onChange: (items: UploadItem[]) => void;
  onPick?: (files: File[]) => void;
  /** `compact` is an Attach button with chips, for composers. */
  variant?: 'dropzone' | 'compact';
  title?: string;
  hint?: string;
  disabled?: boolean;
  id?: string;
  testId?: string;
}) {
  const up = useFileUpload({ purpose, team, retentionClass, multiple });
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [over, setOver] = React.useState(false);
  const onChangeRef = React.useRef(onChange);
  onChangeRef.current = onChange;
  React.useEffect(() => {
    onChangeRef.current(up.items);
  }, [up.items]);

  const accept = up.limit?.allowedTypes.map((t) => `.${t}`).join(',');
  const rule = up.limit ? `${up.limit.allowedTypes.map((t) => t.toUpperCase()).join(', ')} · up to ${up.limit.maxSizeMb} MB${multiple ? ' each' : ''}` : 'Loading limits…';
  const pick = (list: FileList | null) => {
    const files = Array.from(list ?? []);
    if (!files.length) return;
    onPick?.(files);
    up.add(files);
  };

  const input = (
    <input
      ref={inputRef}
      id={id}
      type="file"
      multiple={multiple}
      accept={accept}
      className="sr-only"
      tabIndex={-1}
      disabled={disabled || up.limitsLoading}
      onChange={(e) => {
        pick(e.target.files);
        e.target.value = '';
      }}
    />
  );

  const rows = up.items.length > 0 && (
    <ul className={cn('divide-y rounded-md border', variant === 'compact' && 'border-0 divide-y-0 flex flex-wrap gap-1.5')} data-testid={testId ? `${testId}-items` : undefined}>
      {up.items.map((it) => {
        const Icon = fileIcon(it.name);
        if (variant === 'compact')
          return (
            <li key={it.key} className={cn('inline-flex max-w-full items-center gap-1 rounded-md border bg-muted/40 py-0.5 pr-1 pl-2 text-xs', (it.phase === 'error' || it.phase === 'blocked') && 'border-destructive/40 text-destructive')} data-phase={it.phase} title={it.error}>
              {it.phase === 'ready' ? <Paperclip className="size-3" /> : it.phase === 'error' || it.phase === 'blocked' ? <AlertCircle className="size-3" /> : <Loader2 className="size-3 animate-spin" />}
              <span className="max-w-40 truncate">{it.name}</span>
              <span className="text-muted-foreground tabular-nums">{it.phase === 'uploading' ? `${Math.round(it.progress * 100)}%` : it.phase === 'scanning' ? 'scanning' : bytes(it.size)}</span>
              {it.phase === 'error' && it.retryable && (
                <button type="button" onClick={() => up.retry(it.key)} className="rounded-sm p-0.5 hover:bg-foreground/10" aria-label={`Retry ${it.name}`}>
                  <RotateCcw className="size-3" />
                </button>
              )}
              <button type="button" onClick={() => up.remove(it.key)} className="rounded-sm p-0.5 hover:bg-foreground/10" aria-label={`Remove ${it.name}`}>
                <X className="size-3" />
              </button>
            </li>
          );
        return (
          <li key={it.key} className="flex items-center gap-3 px-3 py-2" data-phase={it.phase}>
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm">
                <span className="truncate font-medium">{it.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{bytes(it.size)}</span>
              </div>
              <div className="text-xs">
                <StatusLine item={it} />
              </div>
              {it.phase === 'uploading' && <Progress value={it.progress * 100} className="mt-1 h-1" aria-label={`Uploading ${it.name}`} />}
            </div>
            {it.deduplicated && it.phase === 'ready' && <Copy className="size-3.5 shrink-0 text-muted-foreground" aria-label="Reused stored copy" />}
            {it.phase === 'error' && it.retryable && (
              <Button variant="ghost" size="sm" className="h-7" onClick={() => up.retry(it.key)}>
                <RotateCcw className="size-3.5" /> Retry
              </Button>
            )}
            <Button variant="ghost" size="icon" className="size-7" onClick={() => up.remove(it.key)} aria-label={`Remove ${it.name}`}>
              <X className="size-3.5" />
            </Button>
          </li>
        );
      })}
    </ul>
  );

  if (variant === 'compact')
    return (
      <div className="flex min-w-0 flex-wrap items-center gap-1.5" data-testid={testId}>
        {input}
        <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={() => inputRef.current?.click()} disabled={disabled || up.limitsLoading} aria-label="Attach files" title={rule}>
          <Paperclip className="size-3.5" /> Attach
        </Button>
        {rows}
      </div>
    );

  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      {input}
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label={`${title ?? (multiple ? 'Choose files' : 'Choose a file')}: ${rule}`}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !disabled) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!disabled) pick(e.dataTransfer.files);
        }}
        className={cn(
          'flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-6 text-center transition-colors hover:bg-muted/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
          over && 'border-primary bg-primary/5',
          disabled && 'cursor-not-allowed opacity-60',
        )}
      >
        <Upload className="size-5 text-muted-foreground" />
        <span className="text-sm font-medium">{title ?? (multiple ? 'Drop files here or choose files' : 'Drop a file here or choose one')}</span>
        <span className="text-xs text-muted-foreground">{rule}</span>
        {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
        {up.scanning && <span className="text-xs text-muted-foreground">Each file is scanned for malware before anyone can open it.</span>}
      </div>
      {rows}
    </div>
  );
}
