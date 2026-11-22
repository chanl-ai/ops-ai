'use client';

import { AlertTriangle, CheckCircle2, CircleDashed, Info, XCircle } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { shortId } from '@/lib/format';
import type { EvalCheck, EvalCheckType, EvalVersionSummary } from '@/lib/types/evals';
import type { SkillCheck } from '@/lib/types/skills';
import { cn } from '@/lib/utils';

export const SOURCE_LABEL: Record<string, string> = { manual: 'Added by hand', csv: 'CSV', test_turn: 'Test panel', review: 'Review' };

export const CHECK_TYPES: { value: EvalCheckType; label: string; hint: string }[] = [
  { value: 'calls_tool', label: 'Calls tool', hint: 'The agent must call this tool.' },
  { value: 'reply_contains', label: 'Reply contains', hint: 'Case-insensitive text the reply must include.' },
  { value: 'refuses', label: 'Refuses (out of scope)', hint: 'The agent must decline or hand off. Name the topic.' },
  { value: 'judge', label: 'Judge', hint: 'A model grades the reply against this rubric. Its cost is part of the run’s.' },
];

/** What a check says in a chip; agent evals and skill tests both draw them, and skill tests carry more types. */
export function checkText(c: EvalCheck | SkillCheck): string {
  switch (c.type) {
    case 'calls_tool':
      return `Calls ${c.tool}${'args' in c && c.args?.length ? ` with ${c.args.map((a) => `${a.path} ${a.equals}`).join(', ')}` : ''}`;
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
    case 'judge':
      return `Judge: ${c.rubric}`;
  }
}

export function CheckChips({ checks, max = 3 }: { checks: (EvalCheck | SkillCheck)[]; max?: number }) {
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
    <span className={cn('inline-flex items-center gap-1.5 text-xs', status === 'pass' ? 'text-success-text' : 'text-destructive-text')}>
      {status === 'pass' ? <CheckCircle2 className="size-3.5 shrink-0" /> : <XCircle className="size-3.5 shrink-0" />}
      {status === 'pass' ? 'Passed' : (detail ?? 'Failed')}
    </span>
  );
}

export function RegressionBadge() {
  return (
    <Badge variant="outline" className="gap-1 border-destructive/40 text-destructive-text">
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
          {summary.regressions > 0 && <span className="text-destructive-text">{summary.regressions === 1 ? '1 regression' : `${summary.regressions} regressions`}</span>}
          <span className={injectionOk ? undefined : 'text-destructive-text'}>
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
