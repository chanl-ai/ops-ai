'use client';

import * as React from 'react';
import { AlertCircle, CheckCircle2, Copy, FolderUp, Loader2, Paperclip, RotateCcw, ShieldX, Upload, X } from 'lucide-react';

import { fileIcon } from '@/components/files/file-meta';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { type UploadItem, useFileUpload } from '@/hooks/file-queries';
import { bytes } from '@/lib/format';
import type { FilePurpose } from '@/lib/types/files';
import { cn } from '@/lib/utils';

export type { UploadItem } from '@/hooks/file-queries';

/**
 * The types and size a purpose accepts, in words. A purpose Settings → Storage sets no limit for takes any type up to the
 * service-wide size, which the console is not told.
 */
export function uploadRule(limit: { allowedTypes: string[]; maxSizeMb: number } | undefined, multiple = true) {
  if (!limit) return 'Any file type';
  return `${limit.allowedTypes.map((t) => t.toUpperCase()).join(', ')} · up to ${limit.maxSizeMb} MB${multiple ? ' each' : ''}`;
}

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

/** Hidden files a folder carries (.DS_Store, Thumbs.db) are left out rather than listed as refused. */
const hidden = (f: File) => f.name.startsWith('.') || f.name === 'Thumbs.db' || f.name === 'desktop.ini';

type Entry = { isFile: boolean; isDirectory: boolean; file?: (ok: (f: File) => void, err: (e: unknown) => void) => void; createReader?: () => { readEntries: (ok: (es: Entry[]) => void, err: (e: unknown) => void) => void } };

async function walk(entry: Entry): Promise<File[]> {
  if (entry.isFile && entry.file) return [await new Promise<File>((ok, err) => entry.file!(ok, err))];
  if (!entry.isDirectory || !entry.createReader) return [];
  const reader = entry.createReader();
  const out: File[] = [];
  // readEntries answers in batches (100 in Chrome) until it answers an empty one.
  for (;;) {
    const batch = await new Promise<Entry[]>((ok, err) => reader.readEntries(ok, err));
    if (!batch.length) break;
    for (const e of batch) out.push(...(await walk(e)));
  }
  return out;
}

/**
 * Every file a drop holds, with each dropped folder walked to the files inside it. `dataTransfer.files` lists a folder
 * as one empty entry, so folders are read through `webkitGetAsEntry`.
 */
export async function filesFromDrop(dt: DataTransfer): Promise<File[]> {
  const entries = Array.from(dt.items ?? [])
    .filter((i) => i.kind === 'file')
    .map((i) => (i as DataTransferItem & { webkitGetAsEntry?: () => Entry | null }).webkitGetAsEntry?.() ?? null);
  if (!entries.length || entries.some((e) => !e)) return Array.from(dt.files);
  const files = (await Promise.all(entries.map((e) => walk(e!)))).flat();
  return files.filter((f) => !hidden(f));
}

/** True when a drag carries files, not text or a link dragged from the page. */
export const dragHasFiles = (e: React.DragEvent | DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files');

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
      <span className="inline-flex items-center gap-1 text-success-text">
        <CheckCircle2 className="size-3" /> {item.deduplicated ? 'Already stored in your team · reused' : 'Uploaded · scan clean'}
      </span>
    );
  if (item.phase === 'blocked')
    return (
      <span className="inline-flex items-center gap-1 text-destructive-text">
        <ShieldX className="size-3" /> {item.error}
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-destructive-text">
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
  types,
  upload,
  others = [],
  shown,
  folder = false,
  initialFiles,
  startWith,
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
  /** Narrows the purpose's allowed extensions for this control, e.g. `['md', 'zip']` for a skill import. */
  types?: string[];
  /** Sends each file somewhere other than Files in one request, as a dev page's mock does; yields its id. */
  upload?: (file: File) => Promise<{ fileId: string }>;
  /** Files attached another way (picked from Files), listed as rows beside the uploads so each file shows once. */
  others?: { key: string; name: string; status: string; onRemove: () => void }[];
  /** Which uploads to list; a caller that no longer holds a finished upload leaves it out. All by default. */
  shown?: (item: UploadItem) => boolean;
  /** Offers "Choose a folder" beside the drop zone; every supported file inside it is added (needs `multiple`). */
  folder?: boolean;
  /** Files already chosen elsewhere (dropped on the page), added once the purpose's limits have loaded. */
  initialFiles?: File[];
  /** Opens the file or folder chooser as soon as the control mounts, for a menu item that names one. */
  startWith?: 'files' | 'folder';
}) {
  const up = useFileUpload({ purpose, team, retentionClass, multiple, upload });
  const inputRef = React.useRef<HTMLInputElement>(null);
  const folderRef = React.useRef<HTMLInputElement>(null);
  const seeded = React.useRef(false);
  React.useEffect(() => {
    // Added after the limits load, so each file is checked against the purpose's types and size.
    if (seeded.current || up.limitsLoading || !initialFiles?.length) return;
    seeded.current = true;
    up.add(initialFiles);
  }, [initialFiles, up.limitsLoading, up.add]);
  React.useEffect(() => {
    if (startWith === 'folder') folderRef.current?.click();
    else if (startWith === 'files') inputRef.current?.click();
    // Once, on mount: the menu click that opened this control is the gesture the chooser needs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const onChangeRef = React.useRef(onChange);
  onChangeRef.current = onChange;
  React.useEffect(() => {
    onChangeRef.current(up.items);
  }, [up.items]);

  const allowed = up.limit ? (types ? up.limit.allowedTypes.filter((t) => types.includes(t)) : up.limit.allowedTypes) : undefined;
  const accept = allowed?.map((t) => `.${t}`).join(',');
  const rule = up.limitsLoading ? 'Loading limits…' : uploadRule(up.limit && allowed ? { allowedTypes: allowed, maxSizeMb: up.limit.maxSizeMb } : undefined, multiple);
  const pick = (list: FileList | File[] | null) => {
    const files = Array.from(list ?? []).filter((f) => !hidden(f));
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
      // Hidden behind the Attach button or the drop zone, but still in the accessibility tree, so it carries a name.
      aria-label={title ?? (multiple ? 'Choose files' : 'Choose a file')}
      disabled={disabled || up.limitsLoading}
      onChange={(e) => {
        pick(e.target.files);
        e.target.value = '';
      }}
    />
  );
  const folderInput = folder && multiple && (
    <input
      ref={folderRef}
      type="file"
      multiple
      className="sr-only"
      tabIndex={-1}
      aria-label="Choose a folder"
      data-testid={testId ? `${testId}-folder` : undefined}
      disabled={disabled || up.limitsLoading}
      // A folder chooser: not in React's typings, so set on the element.
      {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
      onChange={(e) => {
        pick(e.target.files);
        e.target.value = '';
      }}
    />
  );

  const listed = shown ? up.items.filter(shown) : up.items;
  const rows = (listed.length > 0 || others.length > 0) && (
    <ul className={cn('divide-y rounded-md border', variant === 'compact' && 'border-0 divide-y-0 flex flex-wrap gap-1.5')} data-testid={testId ? `${testId}-items` : undefined}>
      {listed.map((it) => {
        const Icon = fileIcon(it.name);
        if (variant === 'compact')
          return (
            <li key={it.key} className={cn('inline-flex max-w-full items-center gap-1 rounded-md border bg-muted/40 py-0.5 pr-1 pl-2 text-xs', (it.phase === 'error' || it.phase === 'blocked') && 'border-destructive/40 text-destructive-text')} data-phase={it.phase} title={it.error}>
              {it.phase === 'ready' ? <Paperclip className="size-3" /> : it.phase === 'error' || it.phase === 'blocked' ? <AlertCircle className="size-3" /> : <Loader2 className="size-3 animate-spin" />}
              <span className="max-w-40 truncate">{it.name}</span>
              {/* A composer has no room for a status line, so the chip itself says why a file was refused. */}
              {it.phase === 'error' || it.phase === 'blocked' ? <span className="max-w-72 break-words">{it.error}</span> : <span className="text-muted-foreground tabular-nums">{it.phase === 'uploading' ? `${Math.round(it.progress * 100)}%` : it.phase === 'scanning' ? 'scanning' : bytes(it.size)}</span>}
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
      {others.map((o) => {
        const Icon = fileIcon(o.name);
        return (
          <li key={o.key} className="flex items-center gap-3 px-3 py-2" data-phase="ready">
            <Icon className="size-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{o.name}</div>
              <div className="inline-flex items-center gap-1 text-xs text-success-text">
                <CheckCircle2 className="size-3" /> {o.status}
              </div>
            </div>
            <Button variant="ghost" size="icon" className="size-7" onClick={o.onRemove} aria-label={`Remove ${o.name}`}>
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

  // A control that holds one file gives way to that file's row once it is chosen; removing it brings the zone back.
  const full = !multiple && (listed.length > 0 || others.length > 0);
  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      {input}
      {folderInput}
      {!full && (
        <DropZone
          title={title ?? (multiple ? 'Drop files here or choose files' : 'Drop a file here or choose one')}
          rule={rule}
          hint={hint}
          scanning={up.scanning}
          disabled={disabled}
          onChoose={() => inputRef.current?.click()}
          onFiles={pick}
        />
      )}
      {folderInput && (
        <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => folderRef.current?.click()} disabled={disabled || up.limitsLoading}>
          <FolderUp className="size-4" /> Choose a folder
        </Button>
      )}
      {rows}
    </div>
  );
}

/**
 * The dashed zone a person drops files or folders on, or clicks to choose them. FileUpload draws it over its own input;
 * a page that opens its upload dialog on a click or a drop draws it alone. A drop is handled here only, so a page-wide
 * drop target around it does not take the same files again.
 */
export function DropZone({ title, rule, hint, scanning, disabled, onChoose, onFiles, testId }: { title: string; rule: string; hint?: string; scanning?: boolean; disabled?: boolean; onChoose: () => void; onFiles: (files: File[]) => void; testId?: string }) {
  const [over, setOver] = React.useState(false);
  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      aria-label={`${title}: ${rule}`}
      data-testid={testId}
      onClick={() => !disabled && onChoose()}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && !disabled) {
          e.preventDefault();
          onChoose();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        setOver(false);
        if (!disabled) void filesFromDrop(e.dataTransfer).then(onFiles);
      }}
      className={cn(
        'flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-dashed px-4 py-6 text-center transition-colors hover:bg-muted/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
        over && 'border-primary bg-primary/5',
        disabled && 'cursor-not-allowed opacity-60',
      )}
    >
      <Upload className="size-5 text-muted-foreground" />
      <span className="text-sm font-medium">{title}</span>
      <span className="text-xs text-muted-foreground">{rule}</span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
      {scanning && <span className="text-xs text-muted-foreground">Each file is scanned for malware before anyone can open it.</span>}
    </div>
  );
}
