'use client';

import Link from 'next/link';
import { AlertTriangle, CheckCircle2, Database, RefreshCw, RotateCcw } from 'lucide-react';

import { KbDot, KbHealthBadge, RunStatusBadge, triggerLabel } from '@/components/knowledge/knowledge-meta';
import { runChecked } from '@/components/sources/run-sheet';
import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows, Section, StatTile } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count, dateTime, duration, plural, relativeTime } from '@/lib/format';
import type { SourceDetail } from '@/lib/types/knowledge';

/** A source at a glance: item counts, the run in progress, who reads it, what is failing, and recent runs. */
export function SourceOverview({
  source: s,
  busy,
  onSync,
  onRetryFailed,
  tabHref,
}: {
  source: SourceDetail;
  busy: boolean;
  onSync: () => void;
  onRetryFailed: () => void;
  tabHref: (tab: string, query?: string) => string;
}) {
  const run = s.running;
  const neverSynced = !s.lastSyncAt && s.recentRuns.length === 0;
  const blocked = s.status === 'revoked';

  return (
    <div className="flex flex-col gap-4">
      {/* A source waiting for its host to be approved says so above; its sync waits too. */}
      {neverSynced && !run && !s.waitingHosts.length && (
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

      {run && (
        <Section title="Current run" description={`${triggerLabel(run.trigger)} · started ${relativeTime(run.startedAt)}`}>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm tabular-nums">
              {run.counts.total !== undefined
                ? `${count(run.counts.checked ?? 0)} of ${plural(run.counts.total, 'item')} checked, ${count(run.counts.failed ?? 0)} failed`
                : `${plural(run.counts.listed ?? 0, 'item')} listed so far, ${count(run.counts.failed ?? 0)} failed`}
            </span>
            {run.counts.total ? <Progress value={((run.counts.checked ?? 0) / run.counts.total) * 100} /> : <Progress value={100} className="animate-pulse" aria-label="Run in progress" />}
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
              <CheckCircle2 className="size-4 text-success-text" /> No failed items.
            </div>
          ) : (
            <Rows>
              {s.errorGroups.map((g) => (
                <Row key={g.message} leading={<AlertTriangle className="size-4 text-destructive-text" />} title={<span className="font-normal">{g.message}</span>} trailing={<span className="text-muted-foreground">{plural(g.count, 'item')}</span>} />
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
                <TableHead className="text-right">Checked</TableHead>
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
                  <TableCell>{triggerLabel(r.trigger)}</TableCell>
                  <TableCell className="text-right tabular-nums">{r.status === 'running' ? '—' : duration(r.durationSec)}</TableCell>
                  <TableCell className="text-right tabular-nums">{count(runChecked(r) ?? 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">{count(r.counts.upserted ?? r.counts.rebuilt ?? 0)}</TableCell>
                  <TableCell className={r.counts.failed ? 'text-right tabular-nums text-destructive-text' : 'text-right tabular-nums'}>{count(r.counts.failed ?? 0)}</TableCell>
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
