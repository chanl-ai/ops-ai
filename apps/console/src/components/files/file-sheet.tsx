'use client';

import * as React from 'react';
import Link from 'next/link';
import { ExternalLink, Lock, Scale, ShieldX, Trash2 } from 'lucide-react';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { DisabledReason } from '@/components/shared/disabled-reason';
import { QueryError } from '@/components/shared/query-states';
import { KeyValues, Row, Rows, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { bytes, dateTime, mimeLabel, relativeTime } from '@/lib/format';
import type { DownloadLink, FileDetail, FilePreview } from '@/lib/types/files';

import { ActionBadge } from '@/components/logs/log-meta';
import { FileDownloadButton } from './file-actions';
import { fileIcon, PURPOSE_LABEL, REF_LABEL, RetentionCell, ScanText, SensitivityBadge } from './file-meta';

function Preview({ preview }: { preview: FilePreview }) {
  if (preview.kind === 'none') return <p className="text-sm text-muted-foreground">{preview.reason}</p>;
  if (preview.kind === 'text') return <pre className="max-h-64 overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs whitespace-pre-wrap">{preview.text}</pre>;
  if (preview.kind === 'pdf')
    return (
      <div className="flex flex-col gap-1.5">
        <div className="max-h-64 overflow-auto rounded-md border bg-white p-4 text-xs leading-relaxed whitespace-pre-wrap text-zinc-800 shadow-xs dark:bg-zinc-900 dark:text-zinc-200">{preview.firstPage}</div>
        <p className="text-xs text-muted-foreground">Page 1 of {preview.pages}</p>
      </div>
    );
  if (preview.kind === 'image')
    return (
      <div className="flex aspect-video max-h-56 items-center justify-center rounded-md border bg-[repeating-conic-gradient(var(--muted)_0%_25%,transparent_0%_50%)] bg-[length:16px_16px] text-xs text-muted-foreground">
        {preview.description} · {preview.width} × {preview.height}
      </div>
    );
  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            {preview.header.map((h) => (
              <TableHead key={h} className="whitespace-nowrap">
                {h}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {preview.rows.map((r, i) => (
            <TableRow key={i}>
              {r.map((c, j) => (
                <TableCell key={j} className="max-w-48 truncate text-xs" title={c}>
                  {c}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="border-t px-3 py-1.5 text-xs text-muted-foreground">First {preview.rows.length} of {preview.totalRows.toLocaleString('en-CA')} rows</p>
    </div>
  );
}

/** One file: preview, metadata, versions, what uses it, its audit trail, and storage for admins. */
export function FileSheet({
  open,
  onOpenChange,
  file,
  loading,
  error,
  onRetry,
  navigation,
  onHold,
  onDelete,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  file?: FileDetail;
  loading: boolean;
  error?: Error | null;
  onRetry: () => void;
  navigation?: DetailSheetNavigation;
  onHold: (f: FileDetail, hold: boolean) => void;
  onDelete: (f: FileDetail) => void;
}) {
  const [link, setLink] = React.useState<DownloadLink | null>(null);
  React.useEffect(() => {
    setLink(null);
  }, [file?.id]);
  const f = file;
  const Icon = f ? fileIcon(f.name) : null;
  const blocked = f && (f.scan.status === 'infected' || f.scan.status === 'failed' ? (f.scan.status === 'infected' ? 'Quarantined: not downloadable' : 'Not scanned, so not downloadable') : f.scan.status === 'pending' ? 'Still being scanned' : undefined);

  return (
    <DetailSheet
      open={open}
      onOpenChange={onOpenChange}
      testId="file-sheet"
      scrollKey={f?.id}
      navigation={navigation}
      title={
        f ? (
          <span className="flex min-w-0 items-center gap-2">
            {Icon && <Icon className="size-4 shrink-0 text-muted-foreground" />}
            <span className="truncate">{f.name}</span>
          </span>
        ) : (
          'File'
        )
      }
      description={f ? `${PURPOSE_LABEL[f.purpose]} · ${bytes(f.size)} · uploaded by ${f.uploadedBy} ${relativeTime(f.uploadedAt)}` : undefined}
      tags={
        f && (
          <>
            <ScanText status={f.scan.status} detail={f.scan.detail} />
            <SensitivityBadge value={f.sensitivity} suggested={f.sensitivitySuggested} />
            {f.legalHold && (
              <Badge variant="outline" className="border-violet-300 font-normal text-violet-800 dark:border-violet-800 dark:text-violet-300">
                <Scale /> Legal hold
              </Badge>
            )}
            {f.immutable && (
              <Badge variant="outline" className="font-normal">
                <Lock /> Immutable
              </Badge>
            )}
          </>
        )
      }
      footerActions={
        f && (
          <>
            <FileDownloadButton fileId={f.id} name={f.name} blocked={blocked} onIssued={setLink} />
            <Button size="sm" variant="outline" onClick={() => onHold(f, !f.legalHold)}>
              <Scale className="size-3.5" /> {f.legalHold ? 'Release hold' : 'Legal hold'}
            </Button>
            <DisabledReason reason={f.deleteBlockedBy ? `Can’t delete: ${f.deleteBlockedBy.charAt(0).toLowerCase()}${f.deleteBlockedBy.slice(1)}` : undefined}>
              <Button size="sm" variant="ghost" className="text-destructive" disabled={!!f.deleteBlockedBy} onClick={() => onDelete(f)}>
                <Trash2 className="size-3.5" /> Delete
              </Button>
            </DisabledReason>
          </>
        )
      }
    >
      {loading && !f ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : error && !f ? (
        <QueryError what="this file" onRetry={onRetry} error={error} />
      ) : f ? (
        <div className="flex flex-col gap-4">
          {f.scan.status === 'infected' && (
            <Alert variant="destructive">
              <ShieldX />
              <AlertTitle>Quarantined</AlertTitle>
              <AlertDescription>The malware scan found {f.scan.detail ?? 'malware'}. Nobody can download or preview it, and records that use it show it as blocked.</AlertDescription>
            </Alert>
          )}
          {link && (
            <Alert>
              <ExternalLink />
              <AlertDescription>Download link issued. It expires in {Math.round(link.ttlSeconds / 60)} minutes and works for this file only; the download is in the audit log.</AlertDescription>
            </Alert>
          )}

          <Section title="Preview">
            <Preview preview={f.preview} />
          </Section>

          <Section title="Details">
            <KeyValues
              rows={[
                ['Purpose', PURPOSE_LABEL[f.purpose]],
                ['Team', f.team],
                ['Type', `${(f.name.split('.').pop() ?? mimeLabel(f.mime)).toUpperCase()} · ${f.mime} · ${bytes(f.size)}`],
                ['Digest', <span key="d" className="font-mono text-xs break-all">sha256:{f.digest}</span>],
                ['Uploaded', `${f.uploadedBy} · ${dateTime(f.uploadedAt)}`],
                ['Scan', `${f.scan.engine ?? '—'}${f.scan.at ? ` · ${relativeTime(f.scan.at)}` : ''}${f.scan.detail ? ` · ${f.scan.detail}` : ''}`],
                ['Retention', <RetentionCell key="r" file={f} />],
                ['Legal hold', f.legalHold ? `${f.legalHold.reason} · ${f.legalHold.by}, ${relativeTime(f.legalHold.at)}` : 'None'],
              ]}
            />
          </Section>

          <Section title={`Used by · ${f.references.length}`} flush>
            {f.references.length ? (
              <Rows>
                {f.references.map((r) => (
                  <Row
                    key={`${r.type}-${r.id}`}
                    href={r.href}
                    leading={<Badge variant="outline" className="font-normal">{REF_LABEL[r.type]}</Badge>}
                    title={r.name}
                    description={r.blocked ? <span className="text-destructive">Blocked · {r.blocked}</span> : `Since ${relativeTime(r.addedAt)}`}
                  />
                ))}
              </Rows>
            ) : (
              <p className="px-4 py-3 text-sm text-muted-foreground">Nothing uses this file. It is deleted when its retention ends, or you can delete it now.</p>
            )}
          </Section>

          <Section title={`Versions · ${f.versions.length}`} flush>
            <Rows>
              {f.versions.map((v) => (
                <Row
                  key={v.version}
                  leading={<span className="font-mono text-xs text-muted-foreground">v{v.version}</span>}
                  title={<span className="font-mono text-xs">sha256:{v.digest.slice(0, 16)}…</span>}
                  description={`${v.uploadedBy} · ${dateTime(v.uploadedAt)}`}
                  trailing={
                    <>
                      <span className="text-xs text-muted-foreground">{bytes(v.size)}</span>
                      {v.current && <Badge variant="secondary">Current</Badge>}
                    </>
                  }
                />
              ))}
            </Rows>
          </Section>

          <Section title="Audit" flush>
            <Rows>
              {f.audit.map((a) => (
                <Row key={a.id} leading={<ActionBadge action={a.action} />} title={a.summary} description={`${a.actor.name} · ${dateTime(a.at)}${a.reason ? ` · ${a.reason}` : ''}`} />
              ))}
            </Rows>
          </Section>

          {f.storage && (
            <Section title="Storage" description="Shown to platform admins only">
              <KeyValues
                rows={[
                  ['Backend', f.storage.backend === 's3' ? 'Amazon S3' : 'Azure Blob Storage'],
                  ['Environment', f.storage.environment],
                  [f.storage.backend === 's3' ? 'Bucket' : 'Container', <span key="c" className="font-mono text-xs">{f.storage.container}</span>],
                  ['Key', <span key="k" className="font-mono text-xs break-all">{f.storage.key}</span>],
                  ['Region', f.storage.region],
                  ['Encryption', f.storage.encryption],
                  ['Lock', f.storage.locked ? (f.storage.backend === 's3' ? 'S3 Object Lock, compliance mode' : 'Locked immutability policy') : 'None'],
                ]}
              />
              <p className="mt-2 text-xs text-muted-foreground">
                Connected through <Link href="/settings/storage" className="underline underline-offset-2">Settings → Storage</Link>.
              </p>
            </Section>
          )}
        </div>
      ) : null}
    </DetailSheet>
  );
}
