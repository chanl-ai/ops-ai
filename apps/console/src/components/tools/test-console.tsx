'use client';

import * as React from 'react';
import { CheckCircle2, CircleAlert, FlaskConical, Lock, Play, ShieldX, UserCheck } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { JsonBlock } from '@/components/shared/json-block';
import { LoadingButton } from '@/components/shared/loading-button';
import { KeyValues, Row, Rows, Section } from '@/components/shared/surface';
import { AccessBadge } from '@/components/status-badges';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { ms } from '@/lib/format';
import type { ModuleOperation, ModuleTestInput, ModuleTestResult, RunContextOption, SchemaField } from '@/lib/types/tool-modules';

import { BINDING_LABEL } from './module-meta';
import { useCan } from '@/hooks/me-queries';

const NO_CONTEXT = 'owner';

const TYPE_HINT: Record<SchemaField['type'], string> = {
  string: 'Text',
  number: 'A number',
  integer: 'A whole number',
  boolean: 'Yes or no',
  object: 'A JSON object, e.g. { "key": "value" }',
  array: 'A list in JSON, e.g. ["a", "b"]',
};

const DENY_LABEL: Record<string, string> = {
  no_approval: 'no approval for this workflow',
  approval_expired: 'approval expired',
  operation_not_approved: 'operation not in the approval',
  operation_hidden: 'operation hidden',
  subject_unbound: 'no record bound to the case',
  subject_mismatch: 'different record from the case',
  constraint: 'over the amount limit',
  approval_token_missing: 'needs an approval token',
  module_not_published: 'module not published',
};

/** A human hint for one generated field: what kind of value, its format, and the schema description. */
const fieldHint = (f: SchemaField) => [f.enum ? 'One of the listed values' : TYPE_HINT[f.type], f.format, f.description].filter(Boolean).join(' · ');

function coerce(f: SchemaField, raw: string): { value?: unknown; error?: string } {
  if (raw.trim() === '') return {};
  if (f.type === 'number' || f.type === 'integer') {
    const n = Number(raw);
    if (Number.isNaN(n) || (f.type === 'integer' && !Number.isInteger(n))) return { error: `Enter ${f.type === 'integer' ? 'a whole number' : 'a number'}.` };
    return { value: n };
  }
  if (f.type === 'boolean') return { value: raw === 'true' };
  if (f.type === 'object' || f.type === 'array') {
    try {
      const v = JSON.parse(raw);
      if (f.type === 'array' && !Array.isArray(v)) return { error: 'Enter a JSON array, e.g. ["a", "b"].' };
      return { value: v };
    } catch {
      return { error: f.type === 'array' ? 'Enter a JSON array, e.g. ["a", "b"].' : 'Enter a JSON object, e.g. { "key": "value" }.' };
    }
  }
  return { value: raw };
}

/** The values typed for one run of `op`, checked against its input schema; a bound input filled by the case is skipped. */
export function useRunValues(op: ModuleOperation | undefined, boundValue?: string) {
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const boundArg = op?.binding?.arg;
  const collect = (): Record<string, unknown> | null => {
    if (!op) return null;
    const input: Record<string, unknown> = {};
    const errs: Record<string, string> = {};
    for (const f of op.input) {
      if (f.name === boundArg && boundValue) continue;
      const raw = values[f.name] ?? '';
      if (f.required && raw.trim() === '') {
        errs[f.name] = f.enum ? 'Choose a value.' : 'Required.';
        continue;
      }
      const c = coerce(f, raw);
      if (c.error) errs[f.name] = c.error;
      else if (c.value !== undefined) input[f.name] = c.value;
    }
    setErrors(errs);
    return Object.keys(errs).length ? null : input;
  };
  const set = (name: string, v: string) => (setValues((x) => ({ ...x, [name]: v })), setErrors(({ [name]: _, ...rest }) => rest));
  return { values, setValues, errors, setErrors, collect, set };
}

/** One field per input of `op`, generated from its schema; a bound input shows the case's value, locked. */
export function RunInputFields({ op, values, errors, onChange, boundValue }: { op: ModuleOperation; values: Record<string, string>; errors: Record<string, string>; onChange: (name: string, value: string) => void; boundValue?: string }) {
  const boundArg = op.binding?.arg;
  return (
    <>
      {!op.input.length && <p className="text-sm text-muted-foreground">This operation takes no input.</p>}
      {op.input.map((f) => {
        const locked = f.name === boundArg && !!boundValue;
        return (
          <FormField
            key={f.name}
            id={`t-${f.name}`}
            label={f.name}
            optional={!f.required && !locked}
            required={f.required && !locked}
            error={errors[f.name]}
            hint={locked ? `Filled from the ${BINDING_LABEL[op.binding!.bindTo].toLowerCase()}. The model cannot change it.` : fieldHint(f)}
          >
            {locked ? (
              <div className="flex h-9 items-center gap-2 rounded-md border bg-muted/50 px-3 font-mono text-sm">
                <Lock className="size-3.5 text-muted-foreground" /> {boundValue}
              </div>
            ) : f.enum ? (
              <Select value={values[f.name] ?? ''} onValueChange={(v) => onChange(f.name, v)}>
                <SelectTrigger id={`t-${f.name}`} className="w-full" aria-invalid={!!errors[f.name]}>
                  <SelectValue placeholder="Choose…" />
                </SelectTrigger>
                <SelectContent>
                  {f.enum.map((e) => (
                    <SelectItem key={e} value={e}>
                      {e}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input id={`t-${f.name}`} value={values[f.name] ?? ''} onChange={(e) => onChange(f.name, e.target.value)} placeholder={f.example ? `e.g. ${f.example}` : undefined} className="font-mono text-sm" aria-invalid={!!errors[f.name]} />
            )}
          </FormField>
        );
      })}
    </>
  );
}

/**
 * Call one operation through the gateway as a workflow would: the approval of the chosen workflow applies and the
 * case's bound fields fill the record inputs. The form is generated from the input schema.
 */
export function TestConsole({
  operations,
  contexts,
  published,
  initialOperation,
  onRun,
  onReset,
  running,
  result,
  error,
  stacked,
  fixedOperation,
}: {
  operations: ModuleOperation[];
  contexts: RunContextOption[];
  published: boolean;
  initialOperation?: string;
  onRun: (input: ModuleTestInput) => void;
  /** Clears the previous response when what it answered (operation, run context, target) changes. */
  onReset: () => void;
  running: boolean;
  result?: ModuleTestResult;
  error?: string;
  /** Request above response, for the side panel beside the module's tabs. */
  stacked?: boolean;
  /** The workbench runs one operation (`initialOperation`), so it shows no operation picker (c-088). */
  fixedOperation?: boolean;
}) {
  const [opName, setOpName] = React.useState(initialOperation ?? operations[0]?.name ?? '');
  const [contextId, setContextId] = React.useState(contexts[0]?.id ?? NO_CONTEXT);
  const [target, setTarget] = React.useState<ModuleTestInput['target']>('stub');
  const cannotRun = useCan('tools', 'run') === false;
  React.useEffect(() => {
    if (initialOperation) setOpName(initialOperation);
  }, [initialOperation]);

  // The first operation of a module that had none, or one removed while chosen: fall back to the first listed.
  React.useEffect(() => {
    if (!operations.some((o) => o.name === opName) && operations[0]) setOpName(operations[0].name);
  }, [operations, opName]);
  const op = operations.find((o) => o.name === opName);
  const ctx = contexts.find((c) => c.id === contextId);
  const boundValue = op?.binding ? ctx?.bindings[op.binding.bindTo] : undefined;
  const { values, setValues, errors, setErrors, collect, set } = useRunValues(op, boundValue);

  React.useEffect(() => {
    setValues({});
    setErrors({});
  }, [opName]); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    onReset();
  }, [opName, contextId, target]); // eslint-disable-line react-hooks/exhaustive-deps
  // Errors the gateway reports for the input land on their fields, like the ones checked before running.
  React.useEffect(() => {
    if (result?.decision === 'invalid' && result.invalid) setErrors(Object.fromEntries(result.invalid.map((x) => [x.field, x.message])));
  }, [result]); // eslint-disable-line react-hooks/exhaustive-deps

  function run(simulateApproval = false) {
    const input = collect();
    if (!op || !input) return;
    onRun({ operation: op.name, contextId: ctx ? ctx.id : NO_CONTEXT, target, input, simulateApproval: simulateApproval || undefined });
  }

  return (
    <div className={stacked ? 'grid gap-4' : 'grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]'}>
      <Section title="Request" description="Runs through the data gateway with the chosen workflow’s approval.">
        <div className="flex flex-col gap-4">
          {!fixedOperation && (
          <FormField id="t-op" label="Operation">
            <Select value={opName} onValueChange={setOpName}>
              <SelectTrigger id="t-op" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {operations.map((o) => (
                  <SelectItem key={o.name} value={o.name}>
                    <span className="font-mono">{o.name}</span>
                    {!o.enabled && <span className="text-xs text-muted-foreground">hidden</span>}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          )}
          <FormField id="t-ctx" label="Run as" hint={published ? 'A sample case from a workflow that requested these tools. Its bound fields fill record inputs.' : 'Not published yet: only the mock runs, as the owner.'}>
            <Select value={contextId} onValueChange={setContextId} disabled={!published || !contexts.length}>
              <SelectTrigger id="t-ctx" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {!published || !contexts.length ? <SelectItem value={NO_CONTEXT}>Owner, no case</SelectItem> : null}
                {contexts.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.workflowName ? `${c.workflowName} · ${c.label}` : c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Target</span>
            <ToggleGroup type="single" variant="outline" value={target} onValueChange={(v) => v && setTarget(v as ModuleTestInput['target'])} className="w-fit">
              <ToggleGroupItem value="stub" className="flex-none px-3 whitespace-nowrap">
                Mock
              </ToggleGroupItem>
              <ToggleGroupItem value="sandbox" className="flex-none px-3 whitespace-nowrap" disabled={!published}>
                Real
              </ToggleGroupItem>
            </ToggleGroup>
            <p className="text-xs text-muted-foreground">{target === 'stub' ? 'Answers from the operation’s mock response. Nothing leaves the gateway.' : 'Calls the app for real through the gateway, writes included, signed in as the app’s Account.'}</p>
          </div>
          {op && (
            <div className="flex flex-col gap-3 border-t pt-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Input</span>
                <AccessBadge access={op.access} />
              </div>
              <RunInputFields op={op} values={values} errors={errors} onChange={set} boundValue={boundValue} />
              {/* Running is its own permission (tools.run): a role without it sees why rather than the refusal. */}
              <LoadingButton isLoading={running} loadingText="Calling…" onClick={() => run()} disabled={cannotRun} className="self-start" data-testid="workbench-run">
                <Play className="size-4" /> Run
              </LoadingButton>
              {cannotRun && <p className="text-xs text-muted-foreground" data-testid="workbench-run-why">Your role can’t run tools; a builder or an admin can.</p>}
            </div>
          )}
        </div>
      </Section>

      <Section title="Response" description={result ? `Test call ${result.callId.slice(-6)}` : 'The gateway’s decision and what the app returned.'}>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : !result ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Run the operation to see the response.</p>
        ) : (
          <ResultBody result={result} op={op} running={running} onSimulate={() => run(true)} />
        )}
      </Section>
    </div>
  );
}

/** A run's answer: the gateway's decision, status and time, what to do about a refusal, and the result tabs. `badge`
 * names where it ran (Mock or Real) on a REST tool's page; `onSimulate` offers a test approval where a workflow's
 * context asks for one. */
export function ResultBody({ result, op, running, onSimulate, badge, labels, brief, tabs, tab, onTab }: { result: ModuleTestResult; op?: ModuleOperation; running: boolean; onSimulate?: () => void; badge?: React.ReactNode; labels?: ResultLabels; brief?: boolean } & TabChoice) {
  return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" data-testid="test-status">
          {badge}
          {result.decision === 'allow' ? (
            <span className="inline-flex items-center gap-1 font-medium text-success-text">
              <CheckCircle2 className="size-4" /> Allowed
            </span>
          ) : result.decision === 'invalid' ? (
            <span className="inline-flex items-center gap-1 font-medium text-warning-text">
              <CircleAlert className="size-4" /> Invalid input · not sent
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 font-medium text-destructive">
              <ShieldX className="size-4" /> Denied · {DENY_LABEL[result.denyReason ?? ''] ?? 'refused by the gateway'}
            </span>
          )}
          <span className="text-muted-foreground tabular-nums">HTTP {result.status}</span>
          <span className="text-muted-foreground tabular-nums">{ms(result.latencyMs)}</span>
          {result.stubbed === false && result.reachedHost && <span className="text-muted-foreground">from {result.reachedHost}</span>}
        </div>
        {result.decision === 'deny' && result.denyMessage && <p className="text-sm">{result.denyMessage}</p>}
        {result.decision === 'invalid' && <p className="text-sm">Fix the highlighted {result.invalid && result.invalid.length === 1 ? 'field' : 'fields'} and run again.</p>}
        {result.denyReason === 'approval_token_missing' && onSimulate && (
          <Alert>
            <FlaskConical className="size-4" />
            <AlertTitle>Simulate the approval</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>Issues a test approval token for this exact input, so the call passes the approval gate and answers from the stub. Test only: it is never accepted in production.</p>
              <Button size="sm" variant="outline" disabled={running} onClick={onSimulate}>
                <UserCheck className="size-4" /> Simulate approval and run
              </Button>
            </AlertDescription>
          </Alert>
        )}
        {result.testApprovalToken && (
          <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className="border-warning/40 bg-warning/10 text-warning-text">
              Test only
            </Badge>
            Ran with a simulated approval token <code className="font-mono text-foreground">{result.testApprovalToken}</code>
          </p>
        )}
        {result.wouldPause && !result.testApprovalToken && brief && (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="waits-for-approval">
            <UserCheck className="size-3.5" /> In a run, an agent&apos;s call waits for {op?.approvers === 2 ? 'two approvals' : 'an approval'}.
          </p>
        )}
        {result.wouldPause && !result.testApprovalToken && !brief && (
          <Alert>
            <UserCheck className="size-4" />
            <AlertTitle>In a run, this call waits for an approval</AlertTitle>
            <AlertDescription>{op?.approvers === 2 ? 'Two different people approve it before the gateway sends it.' : 'The gateway sends it only with an approval token bound to this exact input.'}</AlertDescription>
          </Alert>
        )}
        {result.bound.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Bound:{' '}
            {result.bound.map((b) => (
              <span key={b.arg} className="mr-2">
                <code className="font-mono text-foreground">{b.arg}</code> = <code className="font-mono text-foreground">{b.value}</code> from the {BINDING_LABEL[b.source].toLowerCase()}
              </span>
            ))}
          </p>
        )}
        {result.masked.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Masked: <code className="font-mono">{result.masked.join(', ')}</code>
          </p>
        )}
        {result.transformError && (
          <Alert data-testid="test-transform-error">
            <CircleAlert className="size-4" />
            <AlertTitle>The transform failed</AlertTitle>
            <AlertDescription>{result.transformError} The output is the raw response, as an agent would get it.</AlertDescription>
          </Alert>
        )}
        <ResultTabs result={result} labels={labels} tabs={tabs} tab={tab} onTab={onTab} />
      </div>
  );
}

type ResultLabels = { output: string; request: string };
export type ResultTab = 'output' | 'request' | 'raw' | 'log';
/** Which result tabs show, and the one open when a caller chooses it (a REST tool's page opens Raw and Log from its
 * More menu, c-591). */
type TabChoice = { tabs?: ResultTab[]; tab?: ResultTab; onTab?: (t: ResultTab) => void };

/** The output, and when tools-service sends them (c-088), the request it sent, the answer before the transform and its
 * steps, each on a tab. */
function ResultTabs({ result: r, labels = { output: 'Output', request: 'Request' }, tabs = ['output', 'request', 'raw', 'log'], tab, onTab }: { result: ModuleTestResult; labels?: ResultLabels } & TabChoice) {
  const tone = r.decision === 'deny' || r.status >= 400 ? 'error' : 'default';
  if (!r.request && r.rawResponse === undefined && !r.log?.length) return <JsonBlock value={r.output} tone={tone} maxHeight="22rem" wrap />;
  return (
    <Tabs defaultValue="output" {...(tab ? { value: tab, onValueChange: (v: string) => onTab?.(v as ResultTab) } : {})}>
      <TabsList>
        {tabs.includes('output') && <TabsTrigger value="output">{labels.output}</TabsTrigger>}
        {tabs.includes('request') && <TabsTrigger value="request">{labels.request}</TabsTrigger>}
        {tabs.includes('raw') && <TabsTrigger value="raw">Raw response</TabsTrigger>}
        {tabs.includes('log') && <TabsTrigger value="log">Log</TabsTrigger>}
      </TabsList>
      <TabsContent value="output" className="pt-3">
        <JsonBlock value={r.output} tone={tone} maxHeight="22rem" wrap />
      </TabsContent>
      <TabsContent value="request" className="pt-3" data-testid="test-request">
        {r.request ? (
          <div className="flex flex-col gap-3">
            <KeyValues rows={[['Method', <span key="m" className="font-mono">{r.request.method}</span>], ['URL', <span key="u" className="font-mono break-all">{r.request.url}</span>], ...r.request.headers.map((h): [string, React.ReactNode] => [h.key, <span key={h.key} className="font-mono break-all">{h.value}</span>])]} />
            {r.request.body && <JsonBlock value={r.request.body} maxHeight="12rem" wrap />}
          </div>
        ) : (
          // Say why nothing went out: refused or invalid before sending, a failure before the request, or the mock.
          <p className="text-sm text-muted-foreground" data-testid="test-request-none">
            {r.decision === 'deny'
              ? `Nothing was sent: the call was refused. ${r.denyMessage ?? r.denyReason ?? ''}`.trim()
              : r.decision === 'invalid'
                ? 'Nothing was sent: an input did not fit the tool.'
                : r.stubbed !== true && (r.stubbed === false || r.status >= 400)
                  ? `Nothing was sent: the call stopped before the request went out. ${(r.output as { error?: { message?: string } } | null)?.error?.message ?? ''}`.trim()
                  : 'Nothing was sent: the call answered from the mock.'}
          </p>
        )}
      </TabsContent>
      <TabsContent value="raw" className="pt-3">
        <JsonBlock value={r.rawResponse ?? r.output} maxHeight="22rem" wrap />
      </TabsContent>
      <TabsContent value="log" className="pt-3">
        <Rows testId="test-log">
          {(r.log ?? []).map((l, i) => (
            <Row key={i} leading={<span className="w-16 text-right font-mono text-xs tabular-nums text-muted-foreground">{l.atMs} ms</span>} title={<span className="text-sm">{l.message}</span>} />
          ))}
        </Rows>
      </TabsContent>
    </Tabs>
  );
}
