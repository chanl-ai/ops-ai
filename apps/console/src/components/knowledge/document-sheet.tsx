'use client';

import * as React from 'react';
import { AlertTriangle, BadgeCheck, Copy, ExternalLink, FilePlus2, History, MinusCircle, PauseCircle, RefreshCw, Search, UserRound } from 'lucide-react';

import { FileDownloadButton } from '@/components/files/file-actions';
import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FieldRow, FieldSectionLabel } from '@/components/shared/field-row';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { TagInput } from '@/components/shared/tag-input';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { bytes, count, dateTime, mimeLabel, shortDate, dateOnly } from '@/lib/format';
import type { ItemWithDetail } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

import { ERROR_CLASS_LABEL, FreshnessBadge, ItemStatusBadge, MimeIcon, SensitivityBadge } from './knowledge-meta';

const VERSION_TONE = { current: 'border-emerald-200 text-emerald-700 dark:border-emerald-900 dark:text-emerald-300', superseded: 'text-muted-foreground', scheduled: 'border-blue-200 text-blue-700 dark:border-blue-900 dark:text-blue-300' } as const;
const VERSION_LABEL = { current: 'In force', superseded: 'Superseded', scheduled: 'Scheduled' } as const;

/** One document or source item: its content, chunks, governance metadata and revision history. */
export function DocumentSheet({
  open,
  item,
  loading,
  error,
  onOpenChange,
  navigation,
  owners,
  busy,
  onReprocess,
  onVerify,
  onExclude,
  onSetTags,
  onSetOwner,
  onAddMetadata,
  onOpenItem,
}: {
  open: boolean;
  item?: ItemWithDetail;
  loading: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  navigation?: DetailSheetNavigation;
  owners: string[];
  busy: boolean;
  onReprocess: () => void;
  onVerify: (verified: boolean) => void;
  onExclude: () => void;
  onSetTags: (tags: string[]) => void;
  onSetOwner: (owner: string) => Promise<unknown>;
  onAddMetadata?: () => void;
  /** Opens another item in this sheet, such as an earlier version. */
  onOpenItem?: (id: string) => void;
}) {
  const [chunkQuery, setChunkQuery] = React.useState('');
  const [diffRev, setDiffRev] = React.useState<number | null>(null);
  const [ownerOpen, setOwnerOpen] = React.useState(false);
  const [owner, setOwner] = React.useState('');
  const [tab, setTab] = React.useState('content');
  React.useEffect(() => {
    setChunkQuery('');
    setTab('content');
  }, [item?.id]);

  const d = item?.detail;
  const synced = item && !['file', 'text'].includes(item.sourceType);
  const chunks = d?.chunks.filter((c) => !chunkQuery || `${c.text} ${c.location}`.toLowerCase().includes(chunkQuery.toLowerCase())) ?? [];

  return (
    <>
      <DetailSheet
        open={open}
        onOpenChange={onOpenChange}
        title={item ? <span className="flex items-center gap-2"><MimeIcon mime={item.mimeType} /> <span className="truncate">{item.title}</span></span> : loading ? 'Loading document…' : 'Document'}
        description={item ? <span className="font-mono text-xs">{item.path}</span> : undefined}
        tags={
          item && (
            <>
              <ItemStatusBadge status={item.status} />
              <SensitivityBadge level={item.sensitivity} />
              <FreshnessBadge reviewBy={item.reviewBy} />
              {item.verified && (
                <Badge variant="outline" className="gap-1 font-normal">
                  <BadgeCheck className="size-3 text-emerald-600" /> Verified
                </Badge>
              )}
              <Badge variant="outline" className="font-mono text-[11px] font-normal">
                {item.version}
              </Badge>
            </>
          )
        }
        navigation={navigation}
        scrollKey={item?.id}
        testId="document-sheet"
        footerActions={
          item && (
            <>
              {item.fileId && <FileDownloadButton fileId={item.fileId} name={item.path.split('/').pop() ?? item.title} label="Download original" />}
              <Button size="sm" variant="outline" disabled={busy || item.status === 'excluded'} onClick={onReprocess}>
                <RefreshCw className="size-3.5" /> Reprocess
              </Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => onVerify(!item.verified)}>
                <BadgeCheck className="size-3.5" /> {item.verified ? 'Remove verification' : 'Mark verified'}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setOwner(item.owner);
                  setOwnerOpen(true);
                }}
              >
                <UserRound className="size-3.5" /> Set owner
              </Button>
              <Button size="sm" variant="ghost" className="text-destructive" disabled={busy || item.status === 'excluded'} onClick={onExclude}>
                <MinusCircle className="size-3.5" /> Exclude
              </Button>
            </>
          )
        }
      >
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : !item || !d ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-6 w-48" />
            <Skeleton className="h-40" />
            <Skeleton className="h-24" />
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {item.status === 'failed' && (
              <Alert variant="destructive">
                <AlertTriangle className="size-4" />
                <AlertTitle>{item.error}</AlertTitle>
                <AlertDescription>
                  {item.errorClass ? `${ERROR_CLASS_LABEL[item.errorClass]} error. ` : ''}Fix the file at the source or upload an unlocked copy, then reprocess.
                </AlertDescription>
              </Alert>
            )}
            {item.status === 'held' && item.held && (
              <Alert>
                <PauseCircle className="size-4" />
                <AlertTitle>Held: missing {item.held.missing.join(', ')}</AlertTitle>
                <AlertDescription className="flex flex-col items-start gap-2">
                  <p>
                    {item.held.kbNames.join(', ')} {item.held.kbNames.length === 1 ? 'requires' : 'require'} these fields, so this document is stored but not indexed or searched.
                  </p>
                  {onAddMetadata && (
                    <Button size="sm" variant="outline" onClick={onAddMetadata} disabled={busy}>
                      <FilePlus2 className="size-3.5" /> Add metadata
                    </Button>
                  )}
                </AlertDescription>
              </Alert>
            )}
            {item.status === 'excluded' && (
              <Alert>
                <MinusCircle className="size-4" />
                <AlertTitle>{item.excludedBy ?? 'Excluded'}</AlertTitle>
                <AlertDescription>Change the source’s rules to bring it back; the next sync then indexes it.</AlertDescription>
              </Alert>
            )}
            {item.duplicateOf && (
              <Alert>
                <Copy className="size-4" />
                <AlertTitle>Indexed once, as {item.duplicateOf.title}</AlertTitle>
                <AlertDescription className="flex flex-col items-start gap-2">
                  <p>The content is identical to the copy in {item.duplicateOf.sourceName}, so search returns that one and lists both sources.</p>
                  {onOpenItem && (
                    <Button size="sm" variant="outline" onClick={() => onOpenItem(item.duplicateOf!.itemId)}>
                      Open the indexed copy
                    </Button>
                  )}
                </AlertDescription>
              </Alert>
            )}
            {item.versionStatus === 'superseded' && (
              <Alert>
                <History className="size-4" />
                <AlertTitle>Superseded by {item.supersededBy}</AlertTitle>
                <AlertDescription>Kept and searchable only for questions asked as of a date when this version was in force.</AlertDescription>
              </Alert>
            )}
            {item.url && (
              <Button asChild size="sm" variant="outline" className="w-fit">
                <a href={item.url} target="_blank" rel="noreferrer">
                  <ExternalLink className="size-3.5" /> Open at source
                </a>
              </Button>
            )}
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList>
                <TabsTrigger value="content">Content</TabsTrigger>
                <TabsTrigger value="chunks">
                  Chunks <span className="ml-1 text-muted-foreground">{d.chunks.length}</span>
                </TabsTrigger>
                <TabsTrigger value="metadata">Metadata</TabsTrigger>
                <TabsTrigger value="history">
                  Versions <span className="ml-1 text-muted-foreground">{d.versions.length}</span>
                </TabsTrigger>
              </TabsList>

              <TabsContent value="content" className="flex flex-col gap-3 pt-3">
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {item.pageCount && <span>{item.pageCount} pages</span>}
                  <span>
                    {mimeLabel(item.mimeType)} · {bytes(item.sizeBytes)}
                  </span>
                  <span>Modified at source {shortDate(item.modifiedAt)}</span>
                  <span>From {item.sourceName}</span>
                </div>
                <article className="text-sm">
                  {d.content.split('\n').map((line, i) =>
                    line.startsWith('# ') ? (
                      <h2 key={i} className="mt-2 text-base font-semibold">
                        {line.slice(2)}
                      </h2>
                    ) : line.startsWith('## ') ? (
                      <h3 key={i} className="mt-4 text-sm font-semibold">
                        {line.slice(3)}
                      </h3>
                    ) : line.startsWith('|') ? (
                      <pre key={i} className="overflow-x-auto font-mono text-[11px]">
                        {line}
                      </pre>
                    ) : line ? (
                      <p key={i} className="my-1.5 leading-relaxed">
                        {line}
                      </p>
                    ) : null,
                  )}
                </article>
              </TabsContent>

              <TabsContent value="chunks" className="flex flex-col gap-2 pt-3">
                <div className="relative">
                  <Search className="pointer-events-none absolute top-2 left-2.5 size-3.5 text-muted-foreground" />
                  <Input value={chunkQuery} onChange={(e) => setChunkQuery(e.target.value)} placeholder="Search within chunks" className="h-8 pl-8" aria-label="Search within chunks" />
                </div>
                <ol className="divide-y">
                  {chunks.map((c) => (
                    <li key={c.index} className="flex flex-col gap-1 py-3">
                      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                        <span className="font-mono">#{c.index + 1}</span>
                        <span className="tabular-nums">{c.tokens} tokens</span>
                        <span>{c.location}</span>
                        <Badge variant="outline" className="h-4 px-1 text-[10px] font-normal">
                          {c.kind}
                        </Badge>
                      </div>
                      <p className="text-xs leading-relaxed whitespace-pre-wrap">{c.text}</p>
                    </li>
                  ))}
                  {chunks.length === 0 && <li className="py-6 text-center text-sm text-muted-foreground">No chunks match.</li>}
                </ol>
              </TabsContent>

              <TabsContent value="metadata" className="flex flex-col pt-1">
                <FieldSectionLabel>Governance</FieldSectionLabel>
                <FieldRow label="Owner" value={item.owner} />
                <FieldRow label="Version" value={item.version} mono />
                <FieldRow label="Effective" value={dateOnly(item.effectiveDate)} />
                <FieldRow label="Supersedes" value={item.supersedes} />
                <FieldRow label="Review by" value={dateOnly(item.reviewBy)} />
                <FieldRow label="Collection" value={item.collection} />
                <FieldRow label="Queries · 30d" value={count(item.queries30d)} />
                <FieldSectionLabel>Mapped from the source</FieldSectionLabel>
                {Object.entries(item.metadata).map(([k, val]) => (
                  <FieldRow key={k} label={k} value={val} mono />
                ))}
                <FieldRow label="External id" value={item.externalId} mono />
                <FieldRow label="Content digest" value={item.digest} mono />
                {item.alsoIn?.length ? <FieldRow label="Also in" value={item.alsoIn.map((a) => `${a.title} (${a.sourceName})`).join(', ')} /> : null}
                <FieldSectionLabel>Tags</FieldSectionLabel>
                {synced ? (
                  <div className="flex flex-col gap-1 px-1">
                    <div className="flex flex-wrap gap-1">
                      {item.tags.map((t) => (
                        <Badge key={t} variant="secondary" className="font-normal">
                          {t}
                        </Badge>
                      ))}
                    </div>
                    <p className="text-xs text-muted-foreground">Mapped from the source; change them in the source’s settings.</p>
                  </div>
                ) : (
                  <TagInput value={item.tags} onChange={onSetTags} placeholder="Add tag" disabled={busy} />
                )}
                <FieldSectionLabel>Who can see this document</FieldSectionLabel>
                <div className="flex flex-wrap gap-1 px-1">
                  {item.acl.map((p) => (
                    <Badge key={p} variant="outline" className="font-mono text-[11px] font-normal">
                      {p}
                    </Badge>
                  ))}
                </div>
              </TabsContent>

              <TabsContent value="history" className="flex flex-col gap-3 pt-3">
                <FieldSectionLabel>Versions</FieldSectionLabel>
                <div className="rounded-md border" data-testid="version-history">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Version</TableHead>
                        <TableHead>Effective</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="hidden sm:table-cell">Digest</TableHead>
                        <TableHead />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {d.versions.map((ver) => (
                        <TableRow key={ver.itemId} className={cn(ver.itemId === item.id && 'bg-muted/40')}>
                          <TableCell className="font-mono text-xs">{ver.version}</TableCell>
                          <TableCell className="whitespace-nowrap">{dateOnly(ver.effectiveDate)}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className={cn('font-normal', VERSION_TONE[ver.status])}>
                              {VERSION_LABEL[ver.status]}
                              {ver.supersededBy ? ` by ${ver.supersededBy}` : ''}
                            </Badge>
                          </TableCell>
                          <TableCell className="hidden font-mono text-xs text-muted-foreground sm:table-cell">{ver.digest}</TableCell>
                          <TableCell className="text-right">
                            {ver.itemId === item.id ? (
                              <span className="text-xs text-muted-foreground">Open</span>
                            ) : (
                              onOpenItem && (
                                <Button variant="ghost" size="sm" className="h-7" onClick={() => onOpenItem(ver.itemId)}>
                                  Open
                                </Button>
                              )
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                <FieldSectionLabel>Changes to this version</FieldSectionLabel>
                {synced ? (
                  <ul className="divide-y text-sm">
                    {d.revisions.map((r) => (
                      <li key={r.n} className="flex items-center gap-3 py-2">
                        <History className="size-4 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <div>Sync picked up a change</div>
                          <div className="text-xs text-muted-foreground">
                            {dateTime(r.date)} · {r.sizeDelta >= 0 ? '+' : '−'}
                            {bytes(Math.abs(r.sizeDelta))}
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Revision</TableHead>
                          <TableHead>Author</TableHead>
                          <TableHead>Date</TableHead>
                          <TableHead className="text-right">Size change</TableHead>
                          <TableHead />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {d.revisions.map((r) => (
                          <TableRow key={r.n}>
                            <TableCell className="font-mono text-xs">
                              {r.n}
                              {r.note && (
                                <Badge variant="outline" className="ml-1 h-4 px-1 text-[10px] font-normal">
                                  {r.note}
                                </Badge>
                              )}
                            </TableCell>
                            <TableCell>{r.author}</TableCell>
                            <TableCell className="text-muted-foreground">{shortDate(r.date)}</TableCell>
                            <TableCell className={cn('text-right tabular-nums', r.sizeDelta < 0 && 'text-destructive')}>
                              {r.sizeDelta >= 0 ? '+' : '−'}
                              {bytes(Math.abs(r.sizeDelta))}
                            </TableCell>
                            <TableCell className="text-right">
                              <Button variant="ghost" size="sm" className="h-7" onClick={() => setDiffRev(r.n)}>
                                Compare
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </TabsContent>
            </Tabs>
          </div>
        )}
      </DetailSheet>

      <DialogShell
        open={diffRev !== null}
        onOpenChange={(o) => !o && setDiffRev(null)}
        size="lg"
        title={`Revision ${diffRev} compared with the current version`}
        footer={
          <div className="flex w-full justify-end">
            <Button variant="outline" onClick={() => setDiffRev(null)}>
              Close
            </Button>
          </div>
        }
      >
        <div className="grid gap-3 md:grid-cols-2">
          <pre className="overflow-auto rounded-md border bg-red-50 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap dark:bg-red-950/30">
            {'- Top-up is 85% of base salary for 16 weeks.\n- Employees must have 6 months of service.\n  Requests go through the People portal.'}
          </pre>
          <pre className="overflow-auto rounded-md border bg-emerald-50 p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap dark:bg-emerald-950/30">
            {'+ Top-up is 90% of base salary for 18 weeks (birth parent) and 8 weeks (other parent).\n+ Employees must have 12 months of continuous service.\n  Requests go through the People portal.'}
          </pre>
        </div>
      </DialogShell>

      <DialogShell
        open={ownerOpen}
        onOpenChange={setOwnerOpen}
        size="sm"
        title="Set owner"
        description="The owner is asked to review this document when it goes stale."
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setOwnerOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={busy}
              disabled={!owner || owner === item?.owner}
              onClick={async () => {
                await onSetOwner(owner);
                setOwnerOpen(false);
              }}
            >
              Save owner
            </LoadingButton>
          </div>
        }
      >
        <FormField id="doc-owner" label="Owner">
          <Select value={owner} onValueChange={setOwner}>
            <SelectTrigger id="doc-owner" className="w-full">
              <SelectValue placeholder="Choose an owner" />
            </SelectTrigger>
            <SelectContent>
              {Array.from(new Set([...owners, ...(item ? [item.owner] : [])])).map((o) => (
                <SelectItem key={o} value={o}>
                  {o}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      </DialogShell>
    </>
  );
}
