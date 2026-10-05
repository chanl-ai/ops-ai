'use client';

import { AlertTriangle, CheckCircle2, CircleDashed, Info, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { shortId } from '@/lib/format';
import type { EvalCheck, EvalCheckType, EvalSuiteKind, EvalVersionSummary } from '@/lib/types/evals';
import { cn } from '@/lib/utils';

export const SUITE_LABEL: Record<EvalSuiteKind, string> = {
  agent: 'Agent test set',
  injection: 'Prompt injection',
  leakage: 'Data leakage',
  refusals: 'Refusals and policy topics',
};

export const SOURCE_LABEL: Record<string, string> = { manual: 'Manual', csv: 'CSV', test_turn: 'Test panel', platform: 'Platform' };

export const CHECK_TYPES: { value: EvalCheckType; label: string; hint: string }[] = [
  { value: 'calls_tool', label: 'Calls tool', hint: 'The agent must call this tool, with these arguments when given.' },
  { value: 'not_calls_tool', label: 'Does not call tool', hint: 'Fails if the agent calls this tool.' },
  { value: 'cites', label: 'Cites document', hint: 'The reply must cite this knowledge base, and the section when given.' },
  { value: 'reply_contains', label: 'Reply contains', hint: 'Case-insensitive text the reply must include.' },
  { value: 'reply_not_contains', label: 'Reply must not contain', hint: 'Fails if the reply includes this text.' },
  { value: 'refuses', label: 'Refuses (out of scope)', hint: 'The agent must decline or hand off. Name the topic.' },
  { value: 'extracts', label: 'Extracts field', hint: 'The extracted field must equal this value.' },
  { value: 'rubric', label: 'Rubric (advisory)', hint: 'Advisory: not scored until judge agreement is measured.' },
];

export function checkText(c: EvalCheck): string {
  switch (c.type) {
    case 'calls_tool':
      return `Calls ${c.tool}${c.args?.length ? ` with ${c.args.map((a) => `${a.path} ${a.equals}`).join(', ')}` : ''}`;
    case 'not_calls_tool':
      return `Never calls ${c.tool}`;
    case 'cites':
      return `Cites ${c.section ?? c.source}`;
    case 'reply_contains':
      return `Says “${c.text}”`;
    case 'reply_not_contains':
      return `Never says “${c.text}”`;
    case 'refuses':
      return `Refuses: ${c.text}`;
    case 'extracts':
      return `Extracts ${c.field} as ${c.value}`;
    case 'rubric':
      return `Rubric: ${c.text}`;
  }
}

export function CheckChips({ checks, max = 3 }: { checks: EvalCheck[]; max?: number }) {
  return (
    <div className="flex flex-wrap gap-1">
      {checks.slice(0, max).map((c, i) => (
        <Badge key={i} variant="secondary" className={cn('max-w-64 truncate font-normal', c.type === 'rubric' && 'border-dashed bg-transparent text-muted-foreground')}>
          {checkText(c)}
        </Badge>
      ))}
      {checks.length > max && <span className="text-xs text-muted-foreground">+{checks.length - max}</span>}
    </div>
  );
}

export function OutcomeText({ status, detail }: { status: 'pass' | 'fail' | 'advisory' | null; detail?: string }) {
  if (status === null) return <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"><CircleDashed className="size-3.5" /> Not run</span>;
  if (status === 'advisory')
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Info className="size-3.5" /> Advisory
      </span>
    );
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-xs', status === 'pass' ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
      {status === 'pass' ? <CheckCircle2 className="size-3.5 shrink-0" /> : <XCircle className="size-3.5 shrink-0" />}
      {status === 'pass' ? 'Passed' : (detail ?? 'Failed')}
    </span>
  );
}

export function RegressionBadge() {
  return (
    <Badge variant="outline" className="gap-1 border-red-300 text-red-700 dark:border-red-900 dark:text-red-300">
      <AlertTriangle className="size-3" /> Regression
    </Badge>
  );
}

/** One line for a version's eval result: pass count, regressions and the injection set. */
export function EvalSummaryLine({ summary, className }: { summary: EvalVersionSummary; className?: string }) {
  const injectionOk = summary.injection.passed === summary.injection.total && !summary.injection.regressions;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn('inline-flex flex-wrap items-center gap-x-2 text-xs tabular-nums text-muted-foreground', className)} data-testid="eval-summary-line">
          <span className="font-medium text-foreground">
            Evals {summary.passed}/{summary.total}
          </span>
          {summary.regressions > 0 && <span className="text-red-600 dark:text-red-400">{summary.regressions === 1 ? '1 regression' : `${summary.regressions} regressions`}</span>}
          <span className={injectionOk ? undefined : 'text-red-600 dark:text-red-400'}>
            Injection {summary.injection.passed}/{summary.injection.total}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        Eval run <span className="font-mono">{shortId(summary.runId)}</span>
      </TooltipContent>
    </Tooltip>
  );
}
