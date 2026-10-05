'use client';

import * as React from 'react';
import { CheckCircle2, CircleAlert, FlaskConical, Lock, Play, ShieldX, UserCheck } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { JsonBlock } from '@/components/shared/json-block';
import { LoadingButton } from '@/components/shared/loading-button';
import { Section } from '@/components/shared/surface';
import { AccessBadge } from '@/components/status-badges';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { ms } from '@/lib/format';
import type { ModuleOperation, ModuleTestInput, ModuleTestResult, RunContextOption, SchemaField } from '@/lib/types/tool-modules';

import { BINDING_LABEL } from './module-meta';

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
}) {
  const [opName, setOpName] = React.useState(initialOperation ?? operations[0]?.name ?? '');
  const [contextId, setContextId] = React.useState(contexts[0]?.id ?? NO_CONTEXT);
  const [target, setTarget] = React.useState<ModuleTestInput['target']>('stub');
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  React.useEffect(() => {
    if (initialOperation) setOpName(initialOperation);
  }, [initialOperation]);

  const op = operations.find((o) => o.name === opName);
  const ctx = contexts.find((c) => c.id === contextId);
  const boundArg = op?.binding?.arg;
  const boundValue = op?.binding ? ctx?.bindings[op.binding.bindTo] : undefined;

  React.useEffect(() => {
    setValues({});
    setErrors({});
  }, [opName]);
  React.useEffect(() => {
    onReset();
  }, [opName, contextId, target]); // eslint-disable-line react-hooks/exhaustive-deps
  // Errors the gateway reports for the input land on their fields, like the ones checked before running.
  React.useEffect(() => {
    if (result?.decision === 'invalid' && result.invalid) setErrors(Object.fromEntries(result.invalid.map((x) => [x.field, x.message])));
  }, [result]);

  function collect() {
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
  }

  function run(simulateApproval = false) {
    const input = collect();
    if (!op || !input) return;
    onRun({ operation: op.name, contextId: ctx ? ctx.id : NO_CONTEXT, target, input, simulateApproval: simulateApproval || undefined });
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <Section title="Request" description="Runs through the data gateway with the chosen workflow’s approval.">
        <div className="flex flex-col gap-4">
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
          <FormField id="t-ctx" label="Run as" hint={published ? 'A sample case from a workflow that requested this module. Its bound fields fill record inputs.' : 'Not published yet: only the stub runs, as the module owner.'}>
            <Select value={contextId} onValueChange={setContextId} disabled={!published || !contexts.length}>
              <SelectTrigger id="t-ctx" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {!published || !contexts.length ? <SelectItem value={NO_CONTEXT}>Module owner, no case</SelectItem> : null}
                {contexts.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.workflowName} · {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">Target</span>
            <ToggleGroup type="single" variant="outline" value={target} onValueChange={(v) => v && setTarget(v as ModuleTestInput['target'])} className="w-fit">
              <ToggleGroupItem value="stub" className="flex-none px-3 whitespace-nowrap">
                Stub
              </ToggleGroupItem>
              <ToggleGroupItem value="sandbox" className="flex-none px-3 whitespace-nowrap" disabled={!published}>
                Test environment
              </ToggleGroupItem>
            </ToggleGroup>
            <p className="text-xs text-muted-foreground">{target === 'stub' ? 'Returns the operation’s canned response. Nothing leaves the gateway.' : 'Calls the system’s test environment. Writes need an approval token.'}</p>
          </div>
          {op && (
            <div className="flex flex-col gap-3 border-t pt-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">Input</span>
                <AccessBadge access={op.access} />
              </div>
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
                      <Select value={values[f.name] ?? ''} onValueChange={(v) => (setValues({ ...values, [f.name]: v }), setErrors(({ [f.name]: _, ...rest }) => rest))}>
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
                      <Input id={`t-${f.name}`} value={values[f.name] ?? ''} onChange={(e) => (setValues({ ...values, [f.name]: e.target.value }), setErrors(({ [f.name]: _, ...rest }) => rest))} placeholder={f.example ? `e.g. ${f.example}` : undefined} className="font-mono text-sm" aria-invalid={!!errors[f.name]} />
                    )}
                  </FormField>
                );
              })}
              <LoadingButton isLoading={running} loadingText="Calling…" onClick={() => run()} className="self-start">
                <Play className="size-4" /> Run
              </LoadingButton>
            </div>
          )}
        </div>
      </Section>

      <Section title="Response" description={result ? `Test call ${result.callId.slice(-6)}` : 'The gateway’s decision and what the system returned.'}>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : !result ? (
          <p className="py-10 text-center text-sm text-muted-foreground">Run the operation to see the response.</p>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              {result.decision === 'allow' ? (
                <span className="inline-flex items-center gap-1 font-medium text-emerald-700 dark:text-emerald-400">
                  <CheckCircle2 className="size-4" /> Allowed
                </span>
              ) : result.decision === 'invalid' ? (
                <span className="inline-flex items-center gap-1 font-medium text-amber-700 dark:text-amber-400">
                  <CircleAlert className="size-4" /> Invalid input · not sent
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 font-medium text-red-700 dark:text-red-400">
                  <ShieldX className="size-4" /> Denied · {DENY_LABEL[result.denyReason ?? ''] ?? 'refused by the gateway'}
                </span>
              )}
              <span className="text-muted-foreground tabular-nums">HTTP {result.status}</span>
              <span className="text-muted-foreground tabular-nums">{ms(result.latencyMs)}</span>
            </div>
            {result.decision === 'deny' && result.denyMessage && <p className="text-sm">{result.denyMessage}</p>}
            {result.decision === 'invalid' && <p className="text-sm">Fix the highlighted {result.invalid && result.invalid.length === 1 ? 'field' : 'fields'} and run again.</p>}
            {result.denyReason === 'approval_token_missing' && (
              <Alert>
                <FlaskConical className="size-4" />
                <AlertTitle>Simulate the approval</AlertTitle>
                <AlertDescription className="flex flex-col items-start gap-2">
                  <p>Issues a test approval token for this exact input, so the call reaches the test environment. Test only: it is never accepted in production.</p>
                  <Button size="sm" variant="outline" disabled={running} onClick={() => run(true)}>
                    <UserCheck className="size-4" /> Simulate approval and run
                  </Button>
                </AlertDescription>
              </Alert>
            )}
            {result.testApprovalToken && (
              <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="outline" className="border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300">
                  Test only
                </Badge>
                Ran with a simulated approval token <code className="font-mono text-foreground">{result.testApprovalToken}</code>
              </p>
            )}
            {result.wouldPause && !result.testApprovalToken && (
              <Alert>
                <UserCheck className="size-4" />
                <AlertTitle>In a run, this call waits for an approval</AlertTitle>
                <AlertDescription>{op?.fourEyes ? 'A person approves it, and a second person checks it, before the gateway sends it.' : 'The gateway sends it only with an approval token bound to this exact input.'}</AlertDescription>
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
            <JsonBlock value={result.output} tone={result.decision === 'deny' || result.status >= 400 ? 'error' : 'default'} maxHeight="22rem" wrap />
          </div>
        )}
      </Section>
    </div>
  );
}
