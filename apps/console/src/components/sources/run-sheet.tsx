'use client';

import { Info, RefreshCw, RotateCcw } from 'lucide-react';

import { ERROR_CLASS_LABEL, PHASE_LABEL, PhaseIcon, RunStatusBadge, TRIGGER_LABEL, backoffRetryAt, phaseStatusLabel } from '@/components/knowledge/knowledge-meta';
import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { FieldRow, FieldSectionLabel } from '@/components/shared/field-row';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count, dateTime, duration, ms, relativeTime } from '@/lib/format';
import type { SyncRun } from '@/lib/types/knowledge';

/** One sync run: counts, phases, errors with per-item reprocess, and the raw log. */
export function RunSheet({
  run,
  onOpenChange,
  navigation,
  blocked,
  busy,
  onRetryFailed,
  onRerun,
  onReprocessItem,
}: {
  run: SyncRun | null;
  onOpenChange: (open: boolean) => void;
  navigation?: DetailSheetNavigation;
  /** Why new runs cannot start (connection revoked, another run in progress); undefined when they can. */
  blocked?: string;
  busy: boolean;
  onRetryFailed: () => void;
  onRerun: () => void;
  onReprocessItem: (itemId: string, title: string) => void;
}) {
  const connectionFailure = !!run?.errors.some((e) => e.errorClass === 'permission' && !e.itemId);
  const running = run?.status === 'running';
  const itemErrors = run?.errors.filter((e) => e.itemId) ?? [];

  return (
    <DetailSheet
      open={!!run}
      onOpenChange={onOpenChange}
      title={run ? `Run ${dateTime(run.startedAt)}` : 'Run'}
      description={run && <span className="font-mono text-xs">{run.id}</span>}
      tags={run && <RunStatusBadge status={run.status} />}
      navigation={navigation}
      scrollKey={run?.id}
      testId="run-sheet"
      footerActions={
        run && (
          <>
            <Button size="sm" disabled={busy || !!blocked || connectionFailure || run.counts.failed === 0} onClick={onRetryFailed} title={blocked}>
              <RotateCcw className="size-3.5" /> Retry failed items
            </Button>
            <Button size="sm" variant="outline" disabled={busy || !!blocked} onClick={onRerun} title={blocked}>
              <RefreshCw className="size-3.5" /> Run again
            </Button>
          </>
        )
      }
    >
      {run && (
        <div className="flex flex-col gap-5">
          {blocked && !running && <p className="text-xs text-muted-foreground">New runs can’t start: {blocked.toLowerCase()}.</p>}
          {run.status === 'backing_off' && (
            <Alert>
              <Info className="size-4" />
              <AlertDescription>
                Backing off: the site asked to slow down. The run resumes at {dateTime(backoffRetryAt(run))} ({relativeTime(backoffRetryAt(run))}).
              </AlertDescription>
            </Alert>
          )}
          {run.cursorRejected && (
            <Alert>
              <Info className="size-4" />
              <AlertDescription>The saved cursor was rejected, so a full listing ran and {count(run.counts.deleted)} unseen items were removed.</AlertDescription>
            </Alert>
          )}

          <div>
            <FieldRow label="Trigger" value={TRIGGER_LABEL[run.trigger]} />
            <FieldRow label="Started" value={dateTime(run.startedAt)} />
            <FieldRow label="Duration" value={running ? `${duration(Math.max(0, Math.round((Date.now() - new Date(run.startedAt).getTime()) / 1000)))} so far` : duration(run.durationSec)} />
            <FieldRow label="Cursor before" value={run.cursorBefore} mono />
            <FieldRow label="Cursor after" value={run.cursorAfter} mono />
          </div>

          <div>
            <FieldSectionLabel>Counts</FieldSectionLabel>
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border sm:grid-cols-3">
              {(
                [
                  ['Listed', run.counts.listed],
                  ['Unchanged', run.counts.unchanged],
                  ['Upserted', run.counts.upserted],
                  ['Deleted', run.counts.deleted],
                  ['Failed', run.counts.failed],
                  ['Skipped by rules', run.counts.skipped],
                ] as const
              ).map(([k, v]) => (
                <div key={k} className="bg-card px-3 py-2">
                  <dt className="text-xs text-muted-foreground">{k}</dt>
                  <dd className={k === 'Failed' && v > 0 ? 'text-lg font-semibold tabular-nums text-destructive' : 'text-lg font-semibold tabular-nums'}>{count(v)}</dd>
                </div>
              ))}
            </dl>
          </div>

          <div>
            <FieldSectionLabel>Phases</FieldSectionLabel>
            {running && run.progress && (
              <div className="mb-3 flex flex-col gap-1.5">
                <div className="flex justify-between text-xs tabular-nums text-muted-foreground">
                  <span>
                    {count(run.progress.done)} of {count(run.progress.total)} items, {count(run.progress.failed)} failed
                  </span>
                  <span>{Math.round((run.progress.done / Math.max(run.progress.total, 1)) * 100)}%</span>
                </div>
                <Progress value={(run.progress.done / Math.max(run.progress.total, 1)) * 100} />
              </div>
            )}
            <ol className="divide-y rounded-md border">
              {run.phases.map((p) => (
                <li key={p.name} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <PhaseIcon status={p.status} />
                  <span className="flex-1">{PHASE_LABEL[p.name]}</span>
                  <span className="text-xs text-muted-foreground">{phaseStatusLabel(p.status)}</span>
                  <span className="w-16 text-right text-xs tabular-nums text-muted-foreground">{p.status === 'skipped' ? '—' : ms(p.durationMs)}</span>
                </li>
              ))}
            </ol>
          </div>

          <div>
            <FieldSectionLabel>Errors</FieldSectionLabel>
            {connectionFailure && (
              <Alert variant="destructive" className="mb-3">
                <Info className="size-4" />
                <AlertDescription>{run.errors.find((e) => !e.itemId)?.message}. Retrying items won’t help until the connection is restored.</AlertDescription>
              </Alert>
            )}
            {run.errors.length === 0 ? (
              <p className="text-sm text-muted-foreground">No errors in this run.</p>
            ) : (
              itemErrors.length > 0 && (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Item</TableHead>
                        <TableHead>Phase</TableHead>
                        <TableHead>Class</TableHead>
                        <TableHead>Message</TableHead>
                        <TableHead className="w-10" />
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {itemErrors.map((e, i) => (
                        <TableRow key={`${e.itemId}-${i}`}>
                          <TableCell className="max-w-40 truncate font-medium">{e.itemTitle}</TableCell>
                          <TableCell>{PHASE_LABEL[e.phase]}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="font-normal">
                              {ERROR_CLASS_LABEL[e.errorClass]}
                            </Badge>
                          </TableCell>
                          <TableCell className="max-w-52 text-xs whitespace-normal text-muted-foreground">{e.message}</TableCell>
                          <TableCell>
                            <Button size="sm" variant="ghost" className="h-7" disabled={busy} onClick={() => onReprocessItem(e.itemId, e.itemTitle)}>
                              Reprocess
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )
            )}
          </div>

          <Accordion type="single" collapsible defaultValue={running ? 'log' : undefined}>
            <AccordionItem value="log" className="rounded-md border px-3">
              <AccordionTrigger className="py-2 text-sm">Log · {run.log.length} lines</AccordionTrigger>
              <AccordionContent>
                <pre className="max-h-56 overflow-auto rounded bg-muted/50 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">{run.log.join('\n')}</pre>
              </AccordionContent>
            </AccordionItem>
          </Accordion>
        </div>
      )}
    </DetailSheet>
  );
}
