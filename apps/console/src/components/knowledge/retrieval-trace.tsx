'use client';

import { EyeOff, Filter, Scale, Search, Timer } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ms, plural } from '@/lib/format';
import type { CandidateOutcome, RetrievalTrace } from '@/lib/types/knowledge-retrieval';
import { cn } from '@/lib/utils';

import { MODE_LABEL, OP_LABEL, OUTCOME_LABEL } from './retrieval-meta';

const OUTCOME_TONE: Record<CandidateOutcome, string> = {
  returned: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300',
  below_threshold: 'border-border bg-muted text-muted-foreground',
  over_limit: 'border-border bg-muted text-muted-foreground',
  lost_precedence: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-300',
  superseded: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-300',
  not_in_force: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/50 dark:text-blue-300',
};

const FROM_LABEL = { literal: '', runtime: 'runtime value', preview: 'preview value', unset: 'not set; skipped' } as const;
const score = (n?: number) => (n === undefined ? '—' : n.toFixed(2));
/** Reciprocal rank fusion scores are small (1/61 at best), so they need more places than a relevance score. */
const fusedScore = (n: number) => n.toFixed(4);
const FLAG_LABEL = { superseded: 'Superseded today', stale: 'Stale', scheduled: 'Scheduled', deduplicated: 'Deduplicated', connection_revoked: 'Connection revoked' } as const;

function Block({ icon: Icon, title, children }: { icon: typeof Search; title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h4 className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        <Icon className="size-3.5" /> {title}
      </h4>
      {children}
    </div>
  );
}

/** Everything that decided which passages came back: queries, filters, permissions, scores per stage, the threshold and precedence. */
export function RetrievalTraceView({ trace: t, compact }: { trace: RetrievalTrace; compact?: boolean }) {
  const returned = t.candidates.filter((c) => c.outcome === 'returned').length;
  const fused = t.mode === 'hybrid' || t.mode === 'as_of';
  return (
    <div className="flex flex-col gap-4 text-sm" data-testid="retrieval-trace">
      <div className="flex flex-wrap gap-1.5">
        <Badge variant="secondary" className="font-normal">
          {t.asOf ? `As of ${t.asOf}` : MODE_LABEL[t.mode]}
          {t.mode === 'hybrid' ? ` · semantic ${Math.round(t.hybridWeight * 100)}%` : ''}
        </Badge>
        {t.rerank && (
          <Badge variant="secondary" className="font-normal">
            Reranked
          </Badge>
        )}
        <Badge variant="outline" className="font-normal">
          {t.kbs.map((k) => k.name).join(' + ')}
        </Badge>
        <span className="text-xs text-muted-foreground">{t.settingsFrom}</span>
      </div>

      <Block icon={Search} title="Queries">
        <ol className="flex flex-col gap-1">
          {t.queries.map((q, i) => (
            <li key={i} className="flex items-start gap-2">
              <Badge variant="outline" className="h-5 shrink-0 font-normal capitalize">
                {q.kind}
              </Badge>
              <span className={cn(q.kind === 'original' && t.queries.length > 1 && 'text-muted-foreground')}>{q.text}</span>
            </li>
          ))}
        </ol>
      </Block>

      <Block icon={Filter} title="Filters and permissions">
        <ul className="flex flex-col gap-1">
          {t.filters.conditions.length === 0 && t.filters.tagsInclude.length === 0 && t.filters.tagsExclude.length === 0 && <li className="text-muted-foreground">No filters</li>}
          {t.filters.conditions.map((f, i) => (
            <li key={i} className="flex flex-wrap items-center gap-1.5">
              {i > 0 && <span className="text-xs text-muted-foreground">{t.filters.match === 'all' ? 'and' : 'or'}</span>}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                {f.key} {OP_LABEL[f.op]}
                {f.op !== 'exists' ? ` ${f.value}` : ''}
              </code>
              {f.from !== 'literal' && f.op !== 'exists' && (
                <span className="text-xs">
                  → <span className="font-mono">{f.resolved || '—'}</span> <span className="text-muted-foreground">({FROM_LABEL[f.from]})</span>
                </span>
              )}
            </li>
          ))}
          {t.filters.tagsInclude.length > 0 && <li className="text-xs">Tags include {t.filters.tagsInclude.join(', ')}</li>}
          {t.filters.tagsExclude.length > 0 && <li className="text-xs">Tags exclude {t.filters.tagsExclude.join(', ')}</li>}
        </ul>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>Filters removed {plural(t.filters.removed, 'matching document')}</span>
          {t.hiddenByPermissions !== undefined && (
            <span className="flex items-center gap-1" data-testid="hidden-by-permissions">
              <EyeOff className="size-3" /> {plural(t.hiddenByPermissions, 'matching document')} {t.runAsName ? `${t.runAsName} cannot read` : 'hidden by permissions'}
            </span>
          )}
          <span>{plural(t.searched, 'chunk')} searched</span>
        </div>
      </Block>

      {t.precedence.length > 0 && (
        <Block icon={Scale} title="Precedence">
          <ul className="flex flex-col gap-1">
            {t.precedence.map((d, i) => (
              <li key={i}>
                <span className="font-medium">{d.winner}</span> over <span className="text-muted-foreground line-through decoration-muted-foreground/50">{d.loser}</span>
                <span className="text-xs text-muted-foreground">
                  {' '}
                  · {d.rule} ({d.kbName})
                </span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      <Block icon={Search} title={`Candidates · ${returned} returned · threshold ${t.threshold.toFixed(2)} · limit ${t.chunkLimit}`}>
        {!compact && fused && (
          <p className="text-xs text-muted-foreground">
            Fused ranks by weighted reciprocal rank fusion of the semantic and keyword positions (#). The threshold reads the higher of the semantic and keyword scores. Raise the semantic weight to favour paraphrases, lower it to favour exact codes.
          </p>
        )}
        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Passage</TableHead>
                {!compact && <TableHead className="text-right">Keyword</TableHead>}
                {!compact && <TableHead className="text-right">Semantic</TableHead>}
                {!compact && <TableHead className="text-right">Fused</TableHead>}
                {!compact && t.rerank && <TableHead className="text-right">Reranked</TableHead>}
                <TableHead className="text-right">Final</TableHead>
                <TableHead>Outcome</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {t.candidates.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground">
                    Nothing matched the question.
                  </TableCell>
                </TableRow>
              )}
              {t.candidates.map((c) => (
                <TableRow key={c.chunkId} className={cn(c.outcome !== 'returned' && 'text-muted-foreground')} data-outcome={c.outcome}>
                  <TableCell className="max-w-80 min-w-56 align-top whitespace-normal">
                    <div className="font-medium text-foreground">
                      {c.documentTitle} <span className="font-mono text-[11px] font-normal text-muted-foreground">{c.version}</span>
                    </div>
                    <div className="text-xs">
                      {c.location} · {c.sourceName}
                      {t.kbs.length > 1 ? ` · ${c.kbName}` : ''}
                    </div>
                    {c.note && <div className="text-xs italic">{c.note}</div>}
                    {c.matchedQuery && <div className="text-xs">Best match: “{c.matchedQuery}”</div>}
                  </TableCell>
                  {!compact && (
                    <TableCell className="text-right align-top font-mono text-xs tabular-nums">
                      {score(c.scores.keyword)}
                      {fused && c.scores.keywordRank && <div className="text-muted-foreground">#{c.scores.keywordRank}</div>}
                    </TableCell>
                  )}
                  {!compact && (
                    <TableCell className="text-right align-top font-mono text-xs tabular-nums">
                      {score(c.scores.semantic)}
                      {fused && c.scores.semanticRank && <div className="text-muted-foreground">#{c.scores.semanticRank}</div>}
                    </TableCell>
                  )}
                  {!compact && <TableCell className="text-right align-top font-mono text-xs tabular-nums">{fused ? (c.scores.fused ? fusedScore(c.scores.fused) : '—') : score(c.scores.fused)}</TableCell>}
                  {!compact && t.rerank && <TableCell className="text-right align-top font-mono text-xs tabular-nums">{score(c.scores.reranked)}</TableCell>}
                  <TableCell className="text-right align-top font-mono text-xs font-semibold tabular-nums">{score(c.final)}</TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-col items-start gap-1">
                      <Badge variant="outline" className={cn('font-normal whitespace-nowrap', OUTCOME_TONE[c.outcome])}>
                        {t.asOf && c.outcome === 'returned' ? `In force on ${t.asOf}` : OUTCOME_LABEL[c.outcome]}
                      </Badge>
                      {c.flags
                        .filter((f) => !(f === 'superseded' && c.outcome === 'superseded'))
                        .map((f) => (
                          <Badge key={f} variant="outline" className={cn('font-normal whitespace-nowrap', f === 'connection_revoked' && 'border-destructive/40 text-destructive')}>
                            {FLAG_LABEL[f]}
                          </Badge>
                        ))}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Block>

      <Block icon={Timer} title="Timings">
        <p className="text-xs text-muted-foreground tabular-nums">
          Rewrite {ms(t.timings.rewriteMs)} · search {ms(t.timings.searchMs)} · rerank {ms(t.timings.rerankMs)} · answer {ms(t.timings.synthesisMs)}
        </p>
      </Block>
    </div>
  );
}
