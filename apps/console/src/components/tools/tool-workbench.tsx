'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, KeyRound, Wrench } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { AccessBadge } from '@/components/status-badges';
import { BuilderFieldset, BuilderOnly, ReadOnlyNotice } from '@/components/shared/builder-only';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows, Section } from '@/components/shared/surface';
import { HttpOperationBuilder } from '@/components/tools/http-operation-builder';
import { fieldDrafts, InputSchemaEditor, schemaOf, type FieldDraft } from '@/components/tools/input-schema-editor';
import { unusedInputs } from '@/components/tools/operation-sheet';
import { TestConsole } from '@/components/tools/test-console';
import { Input } from '@/components/ui/input';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import type { HttpOperationInput, ModuleOperation, ModuleTestInput, ModuleTestResult, OperationPatch, RunContextOption } from '@/lib/types/tool-modules';
import { SplitView } from '@/components/shared/setting/split-view';

export interface WorkbenchDraft {
  http: HttpOperationInput;
  input: FieldDraft[];
  stub: string;
  transform: string;
}

const baseOf = (endpoint: string) => endpoint.replace(/\/+$/, '');

export const draftOf = (op: ModuleOperation, endpoint: string): WorkbenchDraft => ({
  http: { name: op.name, description: op.description, access: op.access, method: op.method ?? 'GET', url: `${baseOf(endpoint)}${op.path ?? ''}`, headers: op.headers.map((h) => ({ ...h })), body: op.body ?? '' },
  input: fieldDrafts(op.input),
  stub: op.stub === undefined ? '' : JSON.stringify(op.stub, null, 2),
  transform: op.responseTransform ?? '',
});

/** The mock as JSON, or the reason it is not; an empty box is no mock. */
function parsedStub(text: string): { value?: unknown; error?: string } {
  if (!text.trim()) return {};
  try {
    return { value: JSON.parse(text) };
  } catch (e) {
    return { error: `Not valid JSON: ${(e as Error).message}` };
  }
}

/** A URL off the module's endpoint: a second system is a second module, so it cannot be staged. */
export function urlProblem(d: WorkbenchDraft, endpoint: string): string | undefined {
  const base = baseOf(endpoint);
  return d.http.url !== base && !d.http.url.startsWith(`${base}/`) ? `Keep the module endpoint, ${base}. A second system is a second module.` : undefined;
}

/** What the draft changes against the operation, as a staged edit. */
export function patchOf(op: ModuleOperation, endpoint: string, d: WorkbenchDraft): OperationPatch {
  const before = draftOf(op, endpoint);
  const patch: OperationPatch = {};
  const base = baseOf(endpoint);
  if (d.http.method !== before.http.method) patch.method = d.http.method;
  const path = d.http.url.slice(base.length) || '/';
  if (!urlProblem(d, endpoint) && path !== (op.path ?? '')) patch.path = path;
  const headers = d.http.headers.filter((h) => h.key.trim()).map((h) => ({ key: h.key.trim(), value: h.value.trim() }));
  if (JSON.stringify(headers) !== JSON.stringify(op.headers)) patch.headers = headers;
  if ((d.http.body ?? '').trim() !== (op.body ?? '')) patch.body = (d.http.body ?? '').trim();
  if (JSON.stringify(schemaOf(d.input)) !== JSON.stringify(schemaOf(fieldDrafts(op.input)))) patch.input = schemaOf(d.input);
  if (d.transform.trim() !== (op.responseTransform ?? '')) patch.responseTransform = d.transform.trim() || null;
  const stub = parsedStub(d.stub);
  // A cleared box is null, which tools-service reads as back to the default mock; undefined would drop the key.
  if (!stub.error && d.stub.trim() !== before.stub.trim()) patch.stub = stub.value ?? null;
  return patch;
}

export interface ToolWorkbenchProps {
  moduleId: string;
  moduleName: string;
  endpoint: string;
  op: ModuleOperation;
  /** False when the module is not published: only the mock runs. */
  published: boolean;
  draft: WorkbenchDraft;
  onDraftChange: (d: WorkbenchDraft) => void;
  onStage: () => void;
  staging: boolean;
  /** What staging would change; the Stage button is off when it is empty. */
  dirty: boolean;
  /** Run contexts: the workflows approved for the module, each with a sample case. */
  contexts: RunContextOption[];
  onRun: (input: ModuleTestInput) => void;
  /** Clears the last result when the run's context or target changes. */
  onReset: () => void;
  running: boolean;
  result?: ModuleTestResult;
  /** The run itself failed (the service did not answer); the inputs are kept. */
  runError?: string;
  /** More header actions, before Stage changes (the operation's access and approval policy). */
  extraActions?: React.ReactNode;
  /** The operation's call has a staged change: calls run the published call until the next publish. */
  stagedCall?: boolean;
  /** tools-service's refusal of the input schema, by field name, shown on that row. */
  inputErrors?: Record<string, string>;
}

/**
 * One operation on a full page (c-088): its definition on the left (request, inputs, secrets, mock, transform) and a run
 * on the right, with the request sent, the raw response, the transformed output and the gateway's log side by side. A run
 * uses the draft as it stands, so a transform or mock is tried before it is staged; only staging and publishing change
 * what agents get.
 */
export function ToolWorkbench(p: ToolWorkbenchProps) {
  const { op, draft: d } = p;
  const set = (patch: Partial<WorkbenchDraft>) => p.onDraftChange({ ...d, ...patch });
  const [secretValues, setSecretValues] = React.useState<Record<string, string>>({});
  // A value typed for one run leaves the page when the run ends, whether it answered or failed: React writes a controlled
  // input's value into its `value` attribute, so a kept state keeps the secret in the page's HTML.
  // Below lg the definition and the run are tabs; from lg both show side by side and the tabs are hidden.
  const [view, setView] = React.useState<'definition' | 'run'>('definition');
  const wasRunning = React.useRef(false);
  React.useEffect(() => {
    if (wasRunning.current && !p.running) setSecretValues({});
    wasRunning.current = p.running;
  }, [p.running]);
  const stub = parsedStub(d.stub);
  const urlError = urlProblem(d, p.endpoint);
  const unused = unusedInputs({ ...op, input: schemaOf(d.input).filter((f) => f.name) }, d.http);
  return (
    <PageLayout
      icon={Wrench}
      title={op.name}
      description={
        <span className="flex flex-col gap-0.5">
          <span>{op.description || `${p.moduleName} operation`}</span>
          {op.method && (
            <span className="font-mono text-xs text-muted-foreground" data-testid="op-call">
              {`${op.method} ${op.path}`}
              {p.stagedCall && <span className="font-sans text-warning-text"> · staged; calls run the published call until you publish</span>}
            </span>
          )}
        </span>
      }
      backHref={`/tools/${p.moduleId}`}
      badge={<AccessBadge access={op.access} />}
      actions={
        <>
          {p.extraActions}
          <BuilderOnly>
            <LoadingButton isLoading={p.staging} loadingText="Staging…" onClick={p.onStage} disabled={!p.dirty || !!stub.error || !!urlError} data-testid="workbench-stage">
              Stage changes
            </LoadingButton>
          </BuilderOnly>
        </>
      }
    >
      <ReadOnlyNotice noun="tool modules" />
      <Tabs value={view} onValueChange={(v) => setView(v as 'definition' | 'run')} className="gap-4">
      <TabsList className="w-full lg:hidden" aria-label="Workbench">
        <TabsTrigger value="definition" id="wb-tab-definition" aria-controls="wb-panel-definition">
          Definition
        </TabsTrigger>
        <TabsTrigger value="run" id="wb-tab-run" aria-controls="wb-panel-run">
          Run
        </TabsTrigger>
      </TabsList>
      {/* The tabs sit outside the fieldset: a disabled fieldset disables every button in it, and a viewer must still reach Run. */}
      <BuilderFieldset>
      <div data-testid="tool-workbench"><SplitView id="tool-workbench" defaultLeft={60} leftMin="35" rightMin="25" bare left={
<div id="wb-panel-definition" role="tabpanel" aria-labelledby="wb-tab-definition" className={cn('flex min-w-0 flex-col gap-4', view !== 'definition' && 'max-lg:hidden')}>
          <Section title="Request" description="What the gateway sends. Path, query and headers may read {{SECRET}} and {{field}} values.">
            <div className="flex flex-col gap-4" data-testid="op-http">
              <HttpOperationBuilder value={d.http} onChange={(http) => set({ http })} callOnly errors={{ url: urlError }} />
              {unused.length > 0 && (
                <p className="flex items-start gap-1.5 text-xs text-warning-text" data-testid="op-unused-inputs">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                  <span>
                    {unused.join(', ')} {unused.length === 1 ? 'is an input' : 'are inputs'} of this operation, but the URL, headers and body never use {unused.length === 1 ? 'it' : 'them'}. Agents may send {unused.length === 1 ? 'it' : 'them'} and the call drops {unused.length === 1 ? 'it' : 'them'}.
                  </span>
                </p>
              )}
            </div>
          </Section>
          <Section title="Inputs" description="What an agent may send.">
            <InputSchemaEditor value={d.input} onChange={(input) => set({ input })} boundArg={op.binding?.arg} errors={p.inputErrors} />
          </Section>
          <Section title="Secrets" description="Read from the tenant's secrets. A value typed here is used for this run only and never stored." flush>
            {(op.secrets?.length ?? 0) === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">This operation reads no secrets.</p>
            ) : (
              <Rows testId="workbench-secrets">
                {op.secrets!.map((s) => (
                  <Row
                    key={s.name}
                    leading={<KeyRound className="size-4 text-muted-foreground" />}
                    title={<span className="font-mono text-xs">{s.name}</span>}
                    description={
                      !s.set ? (
                        <Link href="/settings/security/secrets" className="text-warning-text underline-offset-4 hover:underline" data-testid={`secret-unset-${s.name}`}>
                          Not set in this module&apos;s team; set it in Settings
                        </Link>
                      ) : (
                        'Set in this module’s team'
                      )
                    }
                    trailing={<Input type="password" aria-label={`${s.name} test value`} placeholder="Test value" value={secretValues[s.name] ?? ''} onChange={(e) => setSecretValues({ ...secretValues, [s.name]: e.target.value })} className="h-8 w-44 font-mono text-xs" autoComplete="off" />}
                  />
                ))}
              </Rows>
            )}
          </Section>
          <Section title="Mock response" description="Answers a run against the mock, and every write in a test. Staged and reviewed like any edit.">
            <FormField id="wb-stub" label="Response JSON" error={stub.error}>
              <Textarea id="wb-stub" rows={8} value={d.stub} onChange={(e) => set({ stub: e.target.value })} className="font-mono text-xs" placeholder={'{"balance": 1520.33}'} aria-invalid={!!stub.error} />
            </FormField>
          </Section>
          <Section title="Transform" description="A Jinja2 template over the response as data. The run applies it as typed.">
            <FormField id="wb-transform" label="Template" optional error={p.result?.transformError}>
              <Textarea id="wb-transform" rows={5} value={d.transform} onChange={(e) => set({ transform: e.target.value })} className="font-mono text-xs" placeholder={'{"balance": {{ data.balance }}}'} aria-invalid={!!p.result?.transformError} />
            </FormField>
          </Section>
        </div>
} right={
/* The module's test console, fixed to this operation: run as a workflow's case or the owner, against the mock or
            the test environment, with the draft above and any secret values typed here. */
<div id="wb-panel-run" role="tabpanel" aria-labelledby="wb-tab-run" className={cn('min-w-0 lg:sticky lg:top-4 lg:self-start', view !== 'run' && 'max-lg:hidden')} data-testid="module-test-panel">
          <TestConsole
            stacked
            fixedOperation
            operations={[p.op]}
            initialOperation={p.op.name}
            contexts={p.contexts}
            published={p.published}
            onRun={(input) => {
              const typed = Object.fromEntries(Object.entries(secretValues).filter(([, v]) => v !== ''));
              p.onRun({
                ...input,
                // A cleared Transform box is null: run with no transform, not the operation's saved one.
                draft: { responseTransform: d.transform.trim() || null, stub: stub.error ? undefined : stub.value },
                secretValues: Object.keys(typed).length ? typed : undefined,
              });
            }}
            onReset={p.onReset}
            running={p.running}
            result={p.result}
            error={p.runError}
          />
        </div>
} /></div>
      </BuilderFieldset>
      </Tabs>
    </PageLayout>
  );
}

