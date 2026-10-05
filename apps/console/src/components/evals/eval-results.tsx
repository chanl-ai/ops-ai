'use client';

import * as React from 'react';
import { Loader2, Lock } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ms, pct, relativeTime } from '@/lib/format';
import type { EvalCaseResult, EvalRun, EvalSuite, EvalSummary } from '@/lib/types/evals';
import { cn } from '@/lib/utils';

import { OutcomeText, RegressionBadge, SUITE_LABEL } from './eval-meta';

const usd = (n: number) => `$${n.toFixed(2)}`;
const rate = (passed: number, total: number) => (total ? pct(passed / total) : '—');

/** How a run was started, for history rows and sheet headers. */
export const TRIGGER_LABEL: Record<EvalRun['trigger'], string> = { manual: 'Run by hand', save: 'Saved', restore: 'Restored' };

export function versionsLabel(run: Pick<EvalRun, 'draftVersion' | 'compared'>) {
  return run.compared ? `v${run.draftVersion} vs v${run.compared.version} (${run.compared.label})` : `v${run.draftVersion}`;
}

/** Pass rate, regressions, cost and p95 latency, with both versions side by side. */
export function EvalRunSummary({ run }: { run: EvalRun }) {
  if (run.status === 'running' || !run.summary)
    return (
      <div className="flex items-center gap-3 rounded-lg border bg-card px-4 py-4 text-sm" role="status" data-testid="eval-run-running">
        <Loader2 className="size-4 animate-spin text-primary" />
        <span>
          Running {versionsLabel(run)} · started {relativeTime(run.startedAt)} by {run.requestedBy}
        </span>
      </div>
    );
  const s: EvalSummary = run.summary;
  const tiles = [
    { label: 'Pass rate', value: rate(s.passed, s.total), sub: `${s.passed} of ${s.total} cases`, tone: s.passed < s.total ? 'warn' : undefined },
    { label: 'Regressions', value: String(s.regressions), sub: run.compared ? `vs v${run.compared.version}` : 'Nothing to compare', tone: s.regressions ? 'bad' : undefined },
    { label: 'Cost', value: usd(s.costUsd), sub: 'Both versions' },
    { label: 'p95 latency', value: ms(s.p95Ms), sub: 'Per case' },
  ];
  return (
    <div className="flex flex-col gap-3" data-testid="eval-run-summary">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border text-sm md:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="bg-card p-3">
            <div className="text-xs text-muted-foreground">{t.label}</div>
            <div className={cn('text-lg font-semibold tabular-nums', t.tone === 'bad' && 'text-red-600 dark:text-red-400', t.tone === 'warn' && 'text-amber-700 dark:text-amber-400')}>{t.value}</div>
            <div className="text-xs text-muted-foreground">{t.sub}</div>
          </div>
        ))}
      </div>
      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Version</TableHead>
              <TableHead className="text-right">Passed</TableHead>
              <TableHead className="text-right">Pass rate</TableHead>
              <TableHead className="text-right">Cost</TableHead>
              <TableHead className="text-right">p95</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[{ v: s.draft, label: 'Newest' }, ...(s.live && run.compared ? [{ v: s.live, label: run.compared.label === 'live' ? 'Live in workflows' : 'Previous' }] : [])].map(({ v, label }) => (
              <TableRow key={label}>
                <TableCell>
                  <span className="font-mono text-xs font-semibold">v{v.version}</span> <span className="text-xs text-muted-foreground">{label}</span>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {v.passed}/{v.total}
                </TableCell>
                <TableCell className="text-right tabular-nums">{rate(v.passed, v.total)}</TableCell>
                <TableCell className="text-right tabular-nums">{usd(v.costUsd)}</TableCell>
                <TableCell className="text-right tabular-nums">{ms(v.p95Ms)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {s.advisoryChecks > 0 && <p className="text-xs text-muted-foreground">{s.advisoryChecks === 1 ? '1 rubric check was' : `${s.advisoryChecks} rubric checks were`} recorded but not scored. Rubric checks stay advisory until judge agreement with reviewers is measured.</p>}
    </div>
  );
}

/** One card per suite with its pass rate on the newest version. Platform suites are read-only for the agent's owners. */
export function EvalSuiteGrid({ suites }: { suites: EvalSuite[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="eval-suites">
      {suites.map((s) => {
        const failing = s.total !== null && s.passed !== null && s.passed < s.total;
        return (
          <div key={s.kind} className="flex flex-col gap-2 rounded-lg border bg-card p-3">
            <div className="flex items-start justify-between gap-2">
              <span className="text-sm font-medium">{s.name}</span>
              {s.ownedBy === 'platform' && (
                <Badge variant="outline" className="shrink-0 gap-1 text-[10px] font-normal">
                  <Lock className="size-2.5" /> Platform
                </Badge>
              )}
            </div>
            <div className="flex items-baseline gap-2">
              <span className={cn('text-2xl font-semibold tabular-nums', failing && (s.kind === 'injection' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'))}>{s.passed !== null && s.total ? pct(s.passed / s.total) : '—'}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{s.passed !== null ? `${s.passed}/${s.total} passed` : `${s.caseCount} cases, not run`}</span>
            </div>
            {!!s.regressions && <span className="text-xs text-red-600 dark:text-red-400">{s.regressions === 1 ? '1 regression' : `${s.regressions} regressions`}</span>}
            <p className="line-clamp-2 text-xs text-muted-foreground">{s.description}</p>
          </div>
        );
      })}
    </div>
  );
}

/** Per-case results of one run: newest vs compared outcome, regression flag and why it failed. Failing cases first. */
export function EvalResultsTable({ results, compared }: { results: EvalCaseResult[]; compared: EvalRun['compared'] }) {
  const [showAll, setShowAll] = React.useState(false);
  const sorted = [...results].sort((a, b) => Number(b.regression) - Number(a.regression) || Number(b.draft.status === 'fail') - Number(a.draft.status === 'fail'));
  const failing = sorted.filter((r) => r.draft.status === 'fail' || r.regression);
  const shown = showAll ? sorted : failing;
  return (
    <div className="flex flex-col gap-2" data-testid="eval-results">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-muted-foreground">{failing.length ? `${failing.length === 1 ? '1 case needs' : `${failing.length} cases need`} attention` : `All ${results.length} cases passed`}</span>
        <Button variant="ghost" size="sm" onClick={() => setShowAll((x) => !x)}>
          {showAll ? 'Show failing only' : `Show all ${results.length}`}
        </Button>
      </div>
      {shown.length > 0 && (
        <div className="overflow-x-auto rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case</TableHead>
                <TableHead>Suite</TableHead>
                <TableHead>Newest</TableHead>
                <TableHead>{compared ? `v${compared.version} (${compared.label})` : 'Compared'}</TableHead>
                <TableHead>Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((r) => (
                <TableRow key={r.caseId}>
                  <TableCell className="max-w-72">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{r.caseName}</span>
                      {r.regression && <RegressionBadge />}
                    </div>
                    {r.draft.checks.some((c) => c.status === 'advisory') && <div className="text-xs text-muted-foreground">Includes an advisory rubric check</div>}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{SUITE_LABEL[r.suite]}</TableCell>
                  <TableCell className="max-w-80 whitespace-normal">
                    <OutcomeText status={r.draft.status} detail={r.draft.failure} />
                  </TableCell>
                  <TableCell className="max-w-64 whitespace-normal">{r.live ? <OutcomeText status={r.live.status} detail={r.live.failure} /> : <span className="text-xs text-muted-foreground">—</span>}</TableCell>
                  <TableCell className="text-xs tabular-nums text-muted-foreground">{ms(r.draft.latencyMs)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
