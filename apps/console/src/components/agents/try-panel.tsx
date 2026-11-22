'use client';

import * as React from 'react';
import { ChevronDown, FlaskConical, Play, Send, TriangleAlert } from 'lucide-react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { AccountSelect } from '@/components/connections/account-select';
import { EmptyState } from '@/components/shared/empty-state';
import { JsonBlock } from '@/components/shared/json-block';
import { JsonInput } from '@/components/shared/json-input';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { type TryResult, type TryStep, type TryTarget, useTryTargets, useTryTool } from '@/hooks/try-queries';

const SAMPLE_FROM: Record<TryStep['sampleFrom'], string> = {
  last_run: 'From the tool’s last answer in one of your team’s live runs',
  schema: 'From what the tool says it returns; no live run has called it lately',
  none: 'The tool says nothing about what it returns; type a sample',
};

/**
 * One skill path or one workflow step, tried on the account the builder picks. Reads run for real; each write is
 * shown first as what it would send, and is sent only when the builder confirms it, with the live account named when
 * it is one. Sample results stand in for a write that was only planned. Nothing is saved as a version or counted as a
 * run; tools-service decides every call (`POST /v1/tool-modules/tries`).
 */
export function TryPanel({ target, canTry }: { target: TryTarget; canTry: boolean }) {
  const targets = useTryTargets(target);
  const tool = useTryTool();
  const [pathId, setPathId] = React.useState<string>();
  const [accounts, setAccounts] = React.useState<Record<string, string>>();
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [samples, setSamples] = React.useState<Record<string, unknown>>({});
  const [results, setResults] = React.useState<Record<string, TryResult | { error: string }>>({});
  const [running, setRunning] = React.useState(false);

  const data = targets.data;
  const path = data?.paths.find((p) => p.id === pathId) ?? data?.paths[0];
  const picked = accounts ?? path?.steps.find((s) => Object.keys(s.accounts ?? {}).length)?.accounts ?? {};

  if (targets.isPending) {
    return (
      <div className="flex flex-col gap-3" data-testid="try-loading">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }
  if (targets.isError) return <QueryError what="what you can try" onRetry={() => targets.refetch()} retrying={targets.isFetching} error={targets.error} />;
  if (!data || !path) return <EmptyState icon={FlaskConical} title="Nothing to try" description="Write a step that calls a tool, then try it here." />;

  const send = async (step: TryStep, planId?: string) => {
    if (!step.tool) return;
    try {
      const r = await tool.mutateAsync({ tool: step.tool, input: (values[step.key] ?? step.input) as Record<string, never>, accounts: picked, planId });
      setResults((was) => ({ ...was, [step.key]: r }));
    } catch (e) {
      setResults((was) => ({ ...was, [step.key]: { error: (e as Error).message } }));
    }
  };
  const runPath = async () => {
    setRunning(true);
    setResults({});
    for (const step of path.steps) await send(step);
    setRunning(false);
  };

  return (
    <div className="flex flex-col gap-4" data-testid="try-panel">
      {data.paths.length > 1 && (
        <div className="flex flex-col gap-2">
          <Label htmlFor="try-path">Path</Label>
          <Select value={path.id} onValueChange={(v) => (setPathId(v), setResults({}))}>
            <SelectTrigger id="try-path" className="w-full" data-testid="try-path">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {data.paths.map((p) => (
                <SelectItem key={p.id} value={p.id} data-testid={`try-path-${p.id}`}>
                  <span className="truncate">{p.label}</span>
                  <span className="ml-2 text-xs text-muted-foreground">{p.ends === 'done' ? 'to the end' : `ends: ${p.ends}`}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {data.more && <p className="text-xs text-muted-foreground">The skill has more paths than are listed; the first are shown.</p>}
        </div>
      )}
      <div className="flex flex-col gap-2">
        <Label htmlFor="try-account">Account</Label>
        <AccountSelect id="try-account" value={picked} onChange={(v) => (setAccounts(v), setResults({}))} withTestAccounts />
        <p className="text-xs text-muted-foreground">Each app’s default uses its test account when it has one.</p>
      </div>

      <ol className="flex flex-col gap-3">
        {path.steps.map((step) => (
          <StepCard
            key={step.key}
            step={step}
            values={values[step.key] ?? step.input}
            sample={samples[step.key] ?? step.sample}
            onValues={(v) => setValues((was) => ({ ...was, [step.key]: v }))}
            onSample={(v) => setSamples((was) => ({ ...was, [step.key]: v }))}
            result={results[step.key]}
            confirming={tool.isPending}
            onConfirm={(planId) => void send(step, planId)}
          />
        ))}
      </ol>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-muted-foreground">Nothing is saved as a version or counted as a run.</p>
        <LoadingButton isLoading={running} disabled={!canTry || !path.steps.some((s) => s.tool)} onClick={() => void runPath()} data-testid="try-run">
          <Play className="size-4" /> Run
        </LoadingButton>
      </div>
    </div>
  );
}

function StepCard({
  step,
  values,
  sample,
  onValues,
  onSample,
  result,
  confirming,
  onConfirm,
}: {
  step: TryStep;
  values: unknown;
  sample: unknown;
  onValues: (v: unknown) => void;
  onSample: (v: unknown) => void;
  result?: TryResult | { error: string };
  confirming: boolean;
  onConfirm: (planId: string) => void;
}) {
  return (
    <li className="flex flex-col gap-3 rounded-lg border bg-card p-4" data-testid={`try-step-${step.number}`}>
      <div className="flex items-start gap-2">
        <span className="text-sm text-muted-foreground tabular-nums">{step.number}.</span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <p className="text-sm">{step.do}</p>
          {step.test && <p className="text-xs text-muted-foreground">{`If ${step.test}: ${step.holds ? 'yes' : 'no'} on this path`}</p>}
        </div>
        {step.tool && <Badge variant="outline">{step.access === 'write' ? 'Changes something' : 'Reads'}</Badge>}
      </div>
      {!step.tool ? (
        <p className="text-xs text-muted-foreground">The agent does this step itself; a try does not run it.</p>
      ) : (
        <>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`try-values-${step.key}`} className="text-xs">{`Values sent to ${step.tool}`}</Label>
            <JsonInput id={`try-values-${step.key}`} value={values} onChange={onValues} rows={3} placeholder="{}" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor={`try-sample-${step.key}`} className="text-xs">Sample result</Label>
            <JsonInput id={`try-sample-${step.key}`} value={sample} onChange={onSample} rows={3} placeholder="{}" />
            <p className="text-xs text-muted-foreground" data-testid={`try-sample-from-${step.number}`}>{SAMPLE_FROM[step.sampleFrom]}</p>
          </div>
          {result && <Outcome result={result} sample={sample} confirming={confirming} onConfirm={onConfirm} />}
        </>
      )}
    </li>
  );
}

function Outcome({ result, sample, confirming, onConfirm }: { result: TryResult | { error: string }; sample: unknown; confirming: boolean; onConfirm: (planId: string) => void }) {
  if ('error' in result) {
    return (
      <Alert variant="destructive" data-testid="try-error">
        <TriangleAlert />
        <AlertTitle>Couldn’t try it</AlertTitle>
        <AlertDescription>{result.error}</AlertDescription>
      </Alert>
    );
  }
  const where = result.plan?.system ? ` to ${result.plan.system}` : '';
  return (
    <div className="flex flex-col gap-2" data-testid={`try-result-${result.kind}`}>
      {result.kind === 'planned' && result.plan && (
        <Alert data-testid="try-plan">
          <Send />
          <AlertTitle>{result.plan.request ? `Would send ${result.plan.request.method} ${result.plan.request.url}${where}` : `Would call ${result.plan.tool}${where}`}</AlertTitle>
          <AlertDescription>
            <div className="flex w-full flex-col gap-2">
              <span>{`With these values, on ${result.account === 'Default' ? (result.live ? 'the app’s default account, which is live' : 'the app’s test account') : result.live ? `the live account ${result.account}` : `the test account ${result.account}`}. Not sent yet; the sample result stands in for its answer.`}</span>
              <JsonBlock value={result.plan.input} maxHeight="8rem" wrap />
              {result.live && <span className="text-destructive-text">This is a live account: sending changes real records.</span>}
              <div className="flex justify-end">
                <LoadingButton size="sm" variant={result.live ? 'destructive' : 'default'} isLoading={confirming} onClick={() => result.planId && onConfirm(result.planId)} data-testid="try-confirm">
                  {result.live ? 'Send live' : 'Send'}
                </LoadingButton>
              </div>
            </div>
          </AlertDescription>
        </Alert>
      )}
      {result.kind === 'refused' && (
        <Alert variant="destructive" data-testid="try-refused">
          <TriangleAlert />
          <AlertTitle>Not sent</AlertTitle>
          <AlertDescription>{(result.reasons ?? []).join('; ') || 'The gateway refused it.'}</AlertDescription>
        </Alert>
      )}
      {(result.kind === 'ran' || result.kind === 'sent') && (
        <div className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">{result.kind === 'sent' ? (result.replayOf ? 'Sent once already; this is that answer.' : 'Sent. Its answer:') : result.ok ? 'Ran for real. Its answer:' : 'Ran and failed:'}</p>
          <JsonBlock value={result.output} tone={result.ok ? 'default' : 'error'} maxHeight="10rem" wrap />
        </div>
      )}
      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="self-start" data-testid="try-show-steps">
            <ChevronDown className="size-4" /> Show steps
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="flex flex-col gap-2 text-xs">
          <ol className="flex flex-col gap-1 text-muted-foreground">
            {(result.log ?? []).map((l, i) => (
              <li key={i}>
                <span className="tabular-nums">{`${l.atMs} ms`}</span> {l.message}
              </li>
            ))}
            {result.kind === 'planned' && <li>Planned only: no approval asked, no sign-in, nothing sent or logged.</li>}
            {result.kind === 'planned' && <li>Sample result used in place of its answer.</li>}
          </ol>
          {result.request && <JsonBlock value={result.request} maxHeight="8rem" wrap />}
          {result.kind === 'planned' && <JsonBlock value={sample} maxHeight="8rem" wrap />}
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
