'use client';

import Link from 'next/link';
import { AlertTriangle, ArrowRight, CheckCircle2, Loader2, RefreshCw, RotateCcw, XCircle } from 'lucide-react';

import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows, Section, StatTile } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { count, dateTime, duration, plural, relativeTime } from '@/lib/format';
import type { KnowledgeBaseDetail } from '@/lib/types/knowledge';

import { KbHealthBadge, RunStatusBadge, SourceTypeIcon } from './knowledge-meta';

/** Why a knowledge base's health badge says what it says, what it reads, and its recent index jobs. */
export function KbOverview({
  kb,
  busy,
  onRefresh,
  onRetryFailed,
  onCancel,
  tabHref,
}: {
  kb: KnowledgeBaseDetail;
  busy: boolean;
  onRefresh: () => void;
  onRetryFailed: () => void;
  onCancel: () => void;
  tabHref: (tab: string, query?: string) => string;
}) {
  const never = kb.health === 'never';
  const HealthIcon = kb.health === 'healthy' ? CheckCircle2 : kb.health === 'failed' ? XCircle : kb.health === 'indexing' ? Loader2 : AlertTriangle;
  const iconClass = kb.health === 'healthy' ? 'text-emerald-600' : kb.health === 'failed' ? 'text-destructive' : kb.health === 'indexing' ? 'animate-spin text-blue-500' : 'text-amber-500';

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatTile label="Documents" value={count(kb.stats.documents)} hint={plural(kb.sources.length, 'source')} href={tabHref('documents')} />
        <StatTile label="Chunks" value={count(kb.stats.chunks)} hint={kb.stats.documents ? `${(kb.stats.chunks / Math.max(kb.stats.documents, 1)).toFixed(1)} per document` : 'Nothing indexed'} />
        <StatTile label="Last refreshed" value={never ? 'Never' : relativeTime(kb.lastRefreshedAt)} hint={kb.jobs[0]?.trigger ?? 'No jobs yet'} />
        <StatTile label="Failures" value={count(kb.stats.failures)} tone={kb.stats.failures ? 'bad' : 'default'} hint={kb.stats.failures ? 'View failed documents' : 'None'} href={kb.stats.failures ? tabHref('documents', 'status=failed') : undefined} />
        <StatTile label="Stale" value={count(kb.stats.stale)} tone={kb.stats.stale ? 'warn' : 'default'} hint={kb.stats.stale ? 'Past review-by date' : 'None'} href={kb.stats.stale ? tabHref('documents', 'freshness=stale') : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section
          title="Sources"
          description="What this knowledge base reads"
          actions={
            <Button asChild variant="ghost" size="sm" className="h-7">
              <Link href={tabHref('sources')}>
                Manage <ArrowRight className="size-3.5" />
              </Link>
            </Button>
          }
          flush
        >
          <Rows>
            {kb.attached.map((l) => (
              <Row
                key={l.sourceId}
                href={`/sources/${l.sourceId}`}
                leading={<SourceTypeIcon type={l.source.type} />}
                title={l.source.name}
                description={`${plural(l.itemsContributed, 'item')}${l.rules.length ? ` · ${plural(l.rules.length, 'rule')}` : ''} · synced ${relativeTime(l.source.lastSyncAt)}`}
                trailing={<RunStatusBadge status={l.source.status === 'revoked' ? 'failed' : l.source.lastRunStatus} />}
              />
            ))}
            {kb.attached.length === 0 && <li className="px-4 py-6 text-sm text-muted-foreground">This knowledge base reads no sources. Attach one on the Sources tab.</li>}
          </Rows>
        </Section>

        <Section
          title={
            <span className="flex items-center gap-2">
              Health <KbHealthBadge health={kb.health} />
            </span>
          }
          description="Why the badge says what it says"
        >
          {never ? (
            <div className="flex flex-col items-start gap-3 text-sm">
              <p className="text-muted-foreground">Never indexed. Build the index so agents can search it.</p>
              <LoadingButton size="sm" isLoading={busy} onClick={onRefresh} disabled={!kb.sources.length}>
                <RefreshCw className="size-4" /> Build index
              </LoadingButton>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {kb.indexing && (
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2">
                      <Loader2 className="size-4 animate-spin text-muted-foreground" /> Indexing
                    </span>
                    <span className="tabular-nums text-muted-foreground">
                      {count(kb.indexing.done)} of {count(kb.indexing.total)} items
                    </span>
                  </div>
                  <Progress value={(kb.indexing.done / kb.indexing.total) * 100} className="h-1.5" />
                </div>
              )}
              <ul className="flex flex-col gap-1.5 text-sm">
                {kb.healthReasons.map((r) => (
                  <li key={r} className="flex items-start gap-2">
                    <HealthIcon className={`mt-0.5 size-4 shrink-0 ${iconClass}`} />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
              <p className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
                Healthy: the last refresh succeeded with no failures. Degraded: failures, or more than 10% of documents past their review-by date. Failed: the last refresh failed.
              </p>
              <div className="flex flex-wrap gap-2">
                {kb.indexing ? (
                  <LoadingButton size="sm" variant="outline" isLoading={busy} onClick={onCancel}>
                    Cancel refresh
                  </LoadingButton>
                ) : (
                  <>
                    {kb.stats.failures > 0 && (
                      <Button size="sm" variant="outline" disabled={busy} onClick={onRetryFailed}>
                        <RotateCcw className="size-4" /> Retry failed
                      </Button>
                    )}
                    <LoadingButton size="sm" isLoading={busy} onClick={onRefresh}>
                      <RefreshCw className="size-4" /> Refresh index
                    </LoadingButton>
                  </>
                )}
              </div>
            </div>
          )}
        </Section>
      </div>

      <Section title="Precedence" description="When two documents disagree, the answer says which one it followed" flush>
        <ol className="divide-y">
          {kb.precedence.map((p, i) => (
            <li key={p.id} className="flex items-center gap-3 px-4 py-2 text-sm">
              <span className="w-5 text-xs tabular-nums text-muted-foreground">{i + 1}</span>
              <span className="flex-1">{p.label}</span>
              <span className="hidden text-xs text-muted-foreground sm:inline">
                {p.winner} <ArrowRight className="inline size-3" /> {p.loser}
              </span>
            </li>
          ))}
          {kb.precedence.length === 0 && <li className="px-4 py-4 text-sm text-muted-foreground">No precedence rules; the highest-scoring chunk wins.</li>}
        </ol>
        <div className="border-t px-4 py-2 text-xs">
          <Link href={tabHref('retrieval')} className="text-muted-foreground hover:text-foreground">
            Edit on the Retrieval tab
          </Link>
        </div>
      </Section>

      <Section title="Recent index jobs" flush>
        {kb.jobs.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">No jobs yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="pl-4">Started</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead className="text-right">Duration</TableHead>
                <TableHead className="text-right">Processed</TableHead>
                <TableHead className="text-right">Failed</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {kb.jobs.slice(0, 10).map((j) => (
                <TableRow key={j.id}>
                  <TableCell className="pl-4 whitespace-nowrap">{dateTime(j.startedAt)}</TableCell>
                  <TableCell className="text-muted-foreground">{j.trigger}</TableCell>
                  <TableCell className="text-right tabular-nums">{j.status === 'running' ? '—' : duration(j.durationSec)}</TableCell>
                  <TableCell className="text-right tabular-nums">{count(j.processed)}</TableCell>
                  <TableCell className="text-right tabular-nums">{j.failed ? <span className="text-destructive">{count(j.failed)}</span> : '0'}</TableCell>
                  <TableCell>
                    <RunStatusBadge status={j.status} />
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
