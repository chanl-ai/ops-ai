'use client';

import * as React from 'react';

import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ms, pct } from '@/lib/format';
import type { EvalCaseOutcome, EvalCaseResult, EvalRun, EvalRunRow } from '@/lib/types/evals';
import { cn } from '@/lib/utils';

import { OutcomeText, RegressionBadge } from './eval-meta';

/** Run costs are cents: a run of one judged case costs a fraction of one, so small amounts keep four places. */
export const usd = (n: number) => (n > 0 && n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`);

/** How a run was started, for history rows and sheet headers. */
const TRIGGER_LABEL: Record<string, string> = { manual: 'Run evals', publish_request: 'Publish check' };

export const triggerLabel = (trigger: string) => TRIGGER_LABEL[trigger] ?? trigger;

/** The newest version, and the live one it was compared with when that is another. */
export const versionsLabel = (run: Pick<EvalRun, 'version' | 'liveVersion'>) => (run.liveVersion !== null ? `v${run.version} vs v${run.liveVersion} (live)` : `v${run.version}`);

/** The run's cost; a lower bound when a model in it has no price. */
export const costLabel = (run: Pick<EvalRun, 'costUsd' | 'unpriced'>) => (run.unpriced ? `${usd(run.costUsd)}+` : usd(run.costUsd));

/** What failed, in the words of the failing checks; a judge check adds its reason. */
function failure(o: EvalCaseOutcome) {
  const failed = o.checks.filter((c) => c.status === 'fail');
  return failed.length ? failed.map((c) => (c.reason ? `${c.label}: ${c.reason}` : c.label)).join('; ') : undefined;
}

/** Pass rate, regressions and cost of one kept run. */
export function EvalRunSummary({ run }: { run: EvalRunRow }) {
  const s = run.summary;
  const tiles = [
    { label: 'Pass rate', value: s.total ? pct(s.passed / s.total) : '—', sub: `${s.passed} of ${s.total} cases`, tone: s.passed < s.total ? 'warn' : undefined },
    { label: 'Regressions', value: String(s.regressions), sub: run.liveVersion !== null ? `vs v${run.liveVersion}, live` : 'Nothing to compare', tone: s.regressions ? 'bad' : undefined },
    { label: 'Cost', value: costLabel(run), sub: run.unpriced ? 'A model in this run has no price' : 'Cases and judging' },
  ];
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border bg-border text-sm sm:grid-cols-3" data-testid="eval-run-summary">
      {tiles.map((t) => (
        <div key={t.label} className="bg-card p-3">
          <div className="text-xs text-muted-foreground">{t.label}</div>
          <div className={cn('text-lg font-semibold tabular-nums', t.tone === 'bad' && 'text-destructive-text', t.tone === 'warn' && 'text-warning-text')} data-testid={`eval-run-${t.label === 'Cost' ? 'cost' : t.label === 'Pass rate' ? 'pass-rate' : 'regressions'}`}>
            {t.value}
          </div>
          <div className="text-xs text-muted-foreground">{t.sub}</div>
        </div>
      ))}
    </div>
  );
}

/** Per-case results of one run: newest vs live outcome, regression flag and why it failed. Failing cases first. */
export function EvalResultsTable({ results, liveVersion }: { results: EvalCaseResult[]; liveVersion: number | null }) {
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
                <TableHead>Newest</TableHead>
                <TableHead>{liveVersion !== null ? `v${liveVersion} (live)` : 'Compared'}</TableHead>
                <TableHead>Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((r, i) => (
                <TableRow key={`${r.caseName}-${i}`} data-testid="eval-result-row">
                  <TableCell className="max-w-72">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{r.caseName}</span>
                      {r.regression && <RegressionBadge />}
                    </div>
                    {r.unpriced && <div className="text-xs text-muted-foreground">Judge model has no price</div>}
                  </TableCell>
                  <TableCell className="max-w-80 whitespace-normal">
                    <OutcomeText status={r.draft.status} detail={failure(r.draft)} />
                  </TableCell>
                  <TableCell className="max-w-64 whitespace-normal">{r.live ? <OutcomeText status={r.live.status} detail={failure(r.live)} /> : <span className="text-xs text-muted-foreground">—</span>}</TableCell>
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
