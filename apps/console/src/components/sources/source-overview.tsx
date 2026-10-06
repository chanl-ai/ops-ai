'use client';

import Link from 'next/link';
import { AlertTriangle, CheckCircle2, Database, RefreshCw, RotateCcw, Square } from 'lucide-react';

import { KbDot, KbHealthBadge, PHASE_LABEL, PhaseIcon, RunStatusBadge, TRIGGER_LABEL, phaseStatusLabel } from '@/components/knowledge/knowledge-meta';
import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows, Section, StatTile } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count, dateTime, duration, ms, plural, relativeTime } from '@/lib/format';
import type { SourceDetail } from '@/lib/types/knowledge';

/** A source at a glance: item counts, the run in progress, who reads it, what is failing, and recent runs. */
export function SourceOverview({
  source: s,
  busy,
  onSync,
  onRetryFailed,
  onCancel,
  tabHref,
}: {
  source: SourceDetail;
  busy: boolean;
  onSync: () => void;
  onRetryFailed: () => void;
  onCancel: () => void;
  tabHref: (tab: string, query?: string) => string;
}) {
  const run = s.running;
  const neverSynced = !s.lastSyncAt && s.recentRuns.length === 0;
  const blocked = s.status === 'revoked';

  return (
    <div className="flex flex-col gap-4">
      {neverSynced && !run && (
        <Alert>
          <RefreshCw className="size-4" />
          <AlertTitle>This source has not synced yet</AlertTitle>
          <AlertDescription className="flex flex-col items-start gap-2">
            <p>Nothing has been fetched, so no knowledge base can answer from it. The first sync lists every item in scope.</p>
            <LoadingButton size="sm" isLoading={busy} onClick={onSync} disabled={blocked || s.status === 'draft'}>
              <RefreshCw className="size-4" /> Sync now
            </LoadingButton>
          </AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile label="Items indexed" value={count(s.itemsIndexed)} hint="View all items" href={tabHref('items')} />
        <StatTile label="Failed" value={count(s.itemsFailed)} tone={s.itemsFailed > 0 ? 'bad' : 'default'} hint={s.itemsFailed > 0 ? 'View failed items' : 'No failures'} href={s.itemsFailed > 0 ? tabHref('items', 'status=failed') : undefined} />
        <StatTile label="Pending" value={count(s.itemsPending)} hint={s.itemsPending ? 'Waiting for the next run' : 'Nothing waiting'} />
        <StatTile label="Last sync" value={neverSynced ? 'Never' : relativeTime(s.lastSyncAt)} hint={s.lastRunDurationSec !== undefined ? `Took ${duration(s.lastRunDurationSec)}` : 'No runs yet'} />
        <StatTile
          label="Next sync"
          value={s.status === 'paused' ? 'Paused' : blocked ? 'Blocked' : s.schedule.kind === 'manual' || s.status === 'draft' ? 'Manual' : relativeTime(s.nextSyncAt)}
          hint={blocked ? 'Reconnect to resume' : s.status === 'active' && s.nextSyncAt && s.schedule.kind !== 'manual' ? dateTime(s.nextSyncAt) : 'No schedule'}
        />
      </div>

      {run?.progress && (
        <Section
          title="Current run"
          description={`${TRIGGER_LABEL[run.trigger]} · started ${relativeTime(run.startedAt)}`}
          actions={
            <LoadingButton size="sm" variant="outline" isLoading={busy} onClick={onCancel}>
              <Square className="size-3.5" /> Cancel run
            </LoadingButton>
          }
        >
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <div className="flex flex-wrap justify-between gap-2 text-sm">
                <span className="tabular-nums">
                  {count(run.progress.done)} of {plural(run.progress.total, 'item')}, {count(run.progress.failed)} failed
                </span>
                <span className="tabular-nums text-muted-foreground">{Math.round((run.progress.done / Math.max(run.progress.total, 1)) * 100)}%</span>
              </div>
              <Progress value={(run.progress.done / Math.max(run.progress.total, 1)) * 100} />
            </div>
            <ol className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
              {run.phases.map((p) => (
                <li key={p.name} className="flex items-center gap-2 text-sm">
                  <PhaseIcon status={p.status} />
                  <span className="min-w-0">
                    <span className="block truncate">{PHASE_LABEL[p.name]}</span>
                    <span className="block text-xs text-muted-foreground">{p.status === 'skipped' ? phaseStatusLabel(p.status) : ms(p.durationMs)}</span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </Section>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Used by" description={s.readers.length ? `${plural(s.readers.length, 'knowledge base')} read this source` : undefined} flush>
          {s.readers.length === 0 ? (
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-4 text-sm text-muted-foreground">
              <span>No knowledge base reads this source yet.</span>
              <Button asChild size="sm" variant="outline">
                <Link href="/knowledge">Open knowledge bases</Link>
              </Button>
            </div>
          ) : (
            <Rows>
              {s.readers.map((k) => (
                <Row key={k.id} href={`/knowledge/${k.id}`} leading={<KbDot color={k.color} />} title={k.name} description={<span className="font-mono">{k.slug}</span>} trailing={<KbHealthBadge health={k.health} />} />
              ))}
            </Rows>
          )}
        </Section>

        <Section
          title="Errors"
          description={s.errorGroups.length ? 'Most common failure messages across failed items' : undefined}
          actions={
            s.errorGroups.length ? (
              <>
                <Button size="sm" variant="outline" disabled={busy || !!run || blocked} onClick={onRetryFailed}>
                  <RotateCcw className="size-3.5" /> Retry failed
                </Button>
                <Button asChild size="sm" variant="ghost">
                  <Link href={tabHref('items', 'status=failed')}>View items</Link>
                </Button>
              </>
            ) : undefined
          }
          flush
        >
          {s.errorGroups.length === 0 ? (
            <div className="flex items-center gap-2 px-4 py-4 text-sm text-muted-foreground">
              <CheckCircle2 className="size-4 text-emerald-600 dark:text-emerald-400" /> No failed items.
            </div>
          ) : (
            <Rows>
              {s.errorGroups.map((g) => (
                <Row key={g.message} leading={<AlertTriangle className="size-4 text-destructive" />} title={<span className="font-normal">{g.message}</span>} trailing={<span className="text-muted-foreground">{plural(g.count, 'item')}</span>} />
              ))}
            </Rows>
          )}
        </Section>
      </div>

      <Section
        title="Recent runs"
        actions={
          s.recentRuns.length ? (
            <Button asChild size="sm" variant="ghost">
              <Link href={tabHref('history')}>View all</Link>
            </Button>
          ) : undefined
        }
        flush
      >
        {s.recentRuns.length === 0 ? (
          <div className="flex items-center gap-2 px-4 py-4 text-sm text-muted-foreground">
            <Database className="size-4" /> No runs yet. The first sync appears here.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Started</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead className="text-right">Duration</TableHead>
                <TableHead className="text-right">Listed</TableHead>
                <TableHead className="text-right">Changed</TableHead>
                <TableHead className="text-right">Failed</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {s.recentRuns.map((r) => (
                <TableRow key={r.id}>
                  <TableCell className="pl-4 whitespace-nowrap">
                    <Link href={tabHref('history', `run=${r.id}`)} className="hover:underline">
                      {dateTime(r.startedAt)}
                    </Link>
                  </TableCell>
                  <TableCell>{TRIGGER_LABEL[r.trigger]}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.status === 'running' ? '—' : duration(r.durationSec)}</TableCell>
                  <TableCell className="text-right tabular-nums">{count(r.counts.listed)}</TableCell>
                  <TableCell className="text-right tabular-nums">{count(r.counts.upserted + r.counts.deleted)}</TableCell>
                  <TableCell className={r.counts.failed > 0 ? 'text-right tabular-nums text-destructive' : 'text-right tabular-nums'}>{count(r.counts.failed)}</TableCell>
                  <TableCell>
                    <RunStatusBadge status={r.status} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Section>
    </div>
  );
}
