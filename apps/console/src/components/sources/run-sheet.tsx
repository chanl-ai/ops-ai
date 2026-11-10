'use client';

import { RefreshCw, RotateCcw, Square } from 'lucide-react';

import { RunStatusBadge, stepLabel, triggerLabel } from '@/components/knowledge/knowledge-meta';
import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { FieldRow, FieldSectionLabel } from '@/components/shared/field-row';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count, dateTime, duration } from '@/lib/format';
import type { RunCounts, SyncRun } from '@/lib/types/knowledge';

/** What a run looked at: a sync's listing, or the items a settings rebuild has checked. */
export const runChecked = (r: SyncRun) => r.counts.listed ?? r.counts.checked;

/** The model calls and tokens a run's AI steps used, as the run records them; undefined when none ran. */
export function runModelUse(r: SyncRun) {
  const { modelCalls, inputTokens, outputTokens } = r.counts;
  if (!modelCalls) return undefined;
  const tokens = inputTokens !== undefined || outputTokens !== undefined ? ` · ${count(inputTokens ?? 0)} in, ${count(outputTokens ?? 0)} out` : '';
  return `${count(modelCalls)} ${modelCalls === 1 ? 'call' : 'calls'}${tokens}`;
}

const COUNT_LABEL: [keyof RunCounts, string][] = [
  ['listed', 'Listed'],
  ['total', 'To rebuild'],
  ['checked', 'Checked'],
  ['unchanged', 'Unchanged'],
  ['upserted', 'Taken in'],
  ['rebuilt', 'Rebuilt'],
  ['deleted', 'Removed'],
  ['reading', 'Still reading'],
  ['excluded', 'Excluded by rules'],
  ['skipped', 'Skipped'],
  ['failed', 'Failed'],
];

/** One run: its counts, model use, each error with its step and reason, and the log. */
export function RunSheet({
  run,
  onOpenChange,
  navigation,
  blocked,
  busy,
  cancelling,
  onCancel,
  onRetryFailed,
  onFullSync,
}: {
  run: SyncRun | null;
  onOpenChange: (open: boolean) => void;
  navigation?: DetailSheetNavigation;
  /** Why new runs cannot start (connection revoked, another run in progress); undefined when they can. */
  blocked?: string;
  busy: boolean;
  cancelling: boolean;
  onCancel: () => void;
  onRetryFailed: () => void;
  onFullSync: () => void;
}) {
  const running = run?.status === 'running';
  const shown = run ? COUNT_LABEL.filter(([k]) => run.counts[k] !== undefined) : [];
  const model = run && runModelUse(run);

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
        run &&
        (running ? (
          <LoadingButton size="sm" variant="outline" isLoading={cancelling} onClick={onCancel}>
            <Square className="size-3.5" /> Cancel run
          </LoadingButton>
        ) : (
          <>
            <Button size="sm" disabled={busy || !!blocked || !run.counts.failed} onClick={onRetryFailed} title={blocked}>
              <RotateCcw className="size-3.5" /> Retry failed items
            </Button>
            <Button size="sm" variant="outline" disabled={busy || !!blocked} onClick={onFullSync} title={blocked}>
              <RefreshCw className="size-3.5" /> Full resync
            </Button>
          </>
        ))
      }
    >
      {run && (
        <div className="flex flex-col gap-5">
          {blocked && !running && <p className="text-xs text-muted-foreground">New runs can’t start: {blocked.toLowerCase()}.</p>}

          <div>
            <FieldRow label="Trigger" value={triggerLabel(run.trigger)} />
            <FieldRow label="Started" value={dateTime(run.startedAt)} />
            <FieldRow label="Duration" value={running ? 'Running' : duration(run.durationSec)} />
            {run.cancelledBy && <FieldRow label="Cancelled by" value={run.cancelledBy} />}
            <FieldRow label="Model use" value={model ?? 'None'} />
          </div>

          {shown.length > 0 && (
            <div>
              <FieldSectionLabel>Counts</FieldSectionLabel>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border sm:grid-cols-3">
                {shown.map(([k, label]) => {
                  const v = run.counts[k] ?? 0;
                  return (
                    <div key={k} className="bg-card px-3 py-2">
                      <dt className="text-xs text-muted-foreground">{label}</dt>
                      <dd className={k === 'failed' && v > 0 ? 'text-lg font-semibold tabular-nums text-destructive-text' : 'text-lg font-semibold tabular-nums'}>{count(v)}</dd>
                    </div>
                  );
                })}
              </dl>
            </div>
          )}

          <div>
            <FieldSectionLabel>Errors</FieldSectionLabel>
            {run.errors.length === 0 ? (
              <p className="text-sm text-muted-foreground">No errors in this run.</p>
            ) : (
              <div className="rounded-md border" data-testid="run-errors">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Item</TableHead>
                      <TableHead>Step</TableHead>
                      <TableHead>Reason</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {run.errors.map((e, i) => (
                      <TableRow key={`${e.itemId ?? e.itemTitle ?? 'run'}-${i}`}>
                        <TableCell className="max-w-40 truncate font-medium">{e.itemTitle ?? 'The whole run'}</TableCell>
                        <TableCell>{stepLabel(e.phase)}</TableCell>
                        <TableCell className="max-w-64 text-xs whitespace-normal">
                          <Badge variant="outline" className="mr-1 font-normal">
                            {e.errorClass}
                          </Badge>
                          <span className="text-muted-foreground">{e.message}</span>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </div>

          <div>
            <FieldSectionLabel>Log</FieldSectionLabel>
            {run.log.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing logged.</p>
            ) : (
              <ul className="divide-y rounded-md border text-xs" data-testid="run-log">
                {run.log.map((line, i) => (
                  <li key={i} className="px-3 py-1.5 break-words">
                    {line}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </DetailSheet>
  );
}
