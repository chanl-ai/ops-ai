'use client';

import * as React from 'react';
import { CircleAlert, Ellipsis, FlaskConical, Globe, KeyRound, Play, Wrench } from 'lucide-react';

import { PageLayout } from '@/components/page-layout';
import { AccessBadge } from '@/components/status-badges';
import { BuilderFieldset, BuilderOnly, ReadOnlyNotice } from '@/components/shared/builder-only';
import { SignInHeaderNotice } from '@/components/shared/sign-in-header-notice';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Row, Rows, Section } from '@/components/shared/surface';
import { ConnectionSelect, type ConnectionOption } from '@/components/tools/connection-select';
import { BodyEditor, hasBody, HeadersEditor, RequestLine } from '@/components/tools/http-operation-builder';
import { InputSchemaEditor, schemaOf } from '@/components/tools/input-schema-editor';
import { MockAnswers } from '@/components/tools/mock-answers';
import { ResultBody, RunInputFields, useRunValues, type ResultTab } from '@/components/tools/test-console';
import { urlProblem, type WorkbenchDraft } from '@/components/tools/tool-workbench';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useCan } from '@/hooks/me-queries';
import type { ConnectionRef } from '@/lib/types/integrations';
import type { ModuleOperation, ModuleTestInput, ToolRunProps } from '@/lib/types/tool-modules';

type Mode = ModuleTestInput['target'];

const NO_RUN = 'Your role can’t run tools; a builder or an admin can.';

const MODE_BADGE: Record<Mode, React.ReactNode> = {
  stub: (
    <Badge variant="outline" data-testid="run-badge">
      <FlaskConical className="size-3" /> Mock
    </Badge>
  ),
  sandbox: (
    <Badge variant="outline" className="border-warning/30 bg-warning/10 text-warning-text" data-testid="run-badge">
      <Globe className="size-3" /> Real
    </Badge>
  ),
};

export interface RestToolProps extends ToolRunProps {
  moduleId: string;
  /** The tool page's tabs (General, Logs), in the page header's tab slot. */
  tabs?: React.ReactNode;
  /** Shown below the tool's call: who uses the tool. */
  aside?: React.ReactNode;
  moduleName: string;
  /** The app's base address (baseOfApp): the request's address starts with it. */
  base: string;
  op: ModuleOperation;
  /** Real runs only on a published module, on the shape that was reviewed; before that, Run uses Mock. */
  published: boolean;
  draft: WorkbenchDraft;
  onDraftChange: (d: WorkbenchDraft) => void;
  onSave: () => void;
  saving: boolean;
  dirty: boolean;
  /** Every problem the last save was refused for, listed together. */
  saveProblems?: string[];
  connection: ConnectionRef | null;
  connections?: ConnectionOption[];
  connectionsLoading: boolean;
  onConnectionChange: (connectionId: string) => void;
  settingConnection: boolean;
  extraActions?: React.ReactNode;
  stagedCall?: boolean;
  inputErrors?: Record<string, string>;
}

/**
 * A REST tool's operation on one page, in an API client's order (c-591): the connection that signs it in, the method
 * and address with Mock or Real and Run, the inputs, headers and body, then the answer and exactly what was sent, then
 * Save. Mock answers from the operation's mock and sends nothing; Real calls the system with the connection's sign-in.
 */
export function RestTool(p: RestToolProps) {
  const { op, draft: d } = p;
  const set = (patch: Partial<WorkbenchDraft>) => p.onDraftChange({ ...d, ...patch });
  const [mode, setMode] = React.useState<Mode>('stub');
  // Where the last run went, for its badge: a refusal before sending says nothing about it.
  const [ranIn, setRanIn] = React.useState<Mode>('stub');
  const [tab, setTab] = React.useState(hasBody(d.http.method) ? 'body' : 'inputs');
  const [secretValues, setSecretValues] = React.useState<Record<string, string>>({});
  // The answer's tab, Raw response and Log included when More opens them; and the one extra section More shows below.
  const [answerTab, setAnswerTab] = React.useState<ResultTab>('output');
  const [extra, setExtra] = React.useState<'transform' | 'mocks' | null>(null);
  const run = useRunValues(op);
  const urlError = urlProblem(d, p.base);
  // A system with no sign-in runs for real with no connection, as the server allows.
  const realBlocked = !p.published ? 'Real runs once the tool is published. Until then, Run uses Mock.' : undefined;
  // A value typed for one run leaves the page when the run ends: a kept state would keep a secret in the page's HTML.
  const wasRunning = React.useRef(false);
  React.useEffect(() => {
    if (wasRunning.current && !p.running) setSecretValues({});
    wasRunning.current = p.running;
  }, [p.running]);
  React.useEffect(() => {
    if (realBlocked && mode === 'sandbox') setMode('stub');
  }, [realBlocked, mode]);
  React.useEffect(() => {
    if (p.result?.decision === 'invalid' && p.result.invalid) run.setErrors(Object.fromEntries(p.result.invalid.map((x) => [x.field, x.message])));
  }, [p.result]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = () => {
    const input = run.collect();
    if (!input) return;
    setRanIn(mode);
    const typed = Object.fromEntries(Object.entries(secretValues).filter(([, v]) => v !== ''));
    p.onRun({
      operation: op.name,
      contextId: 'owner',
      target: mode,
      input,
      draft: { responseTransform: d.transform.trim() || null },
      secretValues: Object.keys(typed).length ? typed : undefined,
    });
  };
  const host = p.base.replace(/^https?:\/\//, '').split('/')[0];
  // Only a known viewer gets Run below the fields; while the role loads it stays with the address, so nothing moves.
  const viewer = useCan('agents', 'edit') === false;
  // Running a tool is its own permission (tools.run); a role without it sees Run off with the reason, not the refusal.
  const cannotRun = useCan('tools', 'run') === false;
  const runControls = (
    <>
      <ToggleGroup type="single" variant="outline" value={mode} onValueChange={(v) => v && setMode(v as Mode)} aria-label="Run in" data-testid="run-mode">
        <ToggleGroupItem value="stub" className="flex-none px-3">
          Mock
        </ToggleGroupItem>
        <ToggleGroupItem value="sandbox" className="flex-none px-3" disabled={!!realBlocked} title={realBlocked}>
          Real
        </ToggleGroupItem>
      </ToggleGroup>
      <LoadingButton isLoading={p.running} loadingText="Running…" onClick={go} disabled={cannotRun} title={cannotRun ? NO_RUN : undefined} data-testid="run">
        <Play className="size-4" /> Run
      </LoadingButton>
    </>
  );
  const help =
    mode === 'stub'
      ? 'Mock answers from the operation’s mock answers. Nothing leaves the gateway.'
      : `Real sends to ${host} signed in as the app’s Account${op.access === 'write' ? ', so a write changes data there' : ''}.`;

  return (
    <PageLayout
      icon={Wrench}
      title={op.name}
      description={
        <span className="flex flex-col gap-0.5">
          <span>
            {op.description || `${p.moduleName} operation`} · {p.moduleName}
          </span>
          {p.stagedCall && <span className="text-xs text-warning-text">Saved; Real runs the published call until you publish.</span>}
        </span>
      }
      backHref={`/tools/${p.moduleId}`}
      tabs={p.tabs}
      badge={<AccessBadge access={op.access} />}
      actions={
        <>
          {p.extraActions}
          <BuilderOnly>
            <LoadingButton isLoading={p.saving} loadingText="Saving…" onClick={p.onSave} disabled={!p.dirty || !!urlError} data-testid="workbench-stage">
              Save
            </LoadingButton>
          </BuilderOnly>
        </>
      }
    >
      <ReadOnlyNotice noun="tools" />
      <SignInHeaderNotice header={p.op.signInHeader} />
      {p.saveProblems && p.saveProblems.length > 0 && (
        <Alert variant="destructive" data-testid="save-problems">
          <CircleAlert className="size-4" />
          <AlertTitle>{p.saveProblems.length === 1 ? 'Couldn’t save' : `Couldn’t save: ${p.saveProblems.length} problems`}</AlertTitle>
          <AlertDescription>
            <ul className="ml-4 list-disc">
              {p.saveProblems.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
            <p>Your edits are kept.</p>
          </AlertDescription>
        </Alert>
      )}
      <div className="flex flex-col gap-4" data-testid="module-test-panel">
        <Section title="Request" description="Pick the app, write the call, then Run it in Mock or Real.">
          <BuilderFieldset>
            <div className="flex flex-col gap-4" data-testid="op-http">
              <FormField
                id="rest-conn"
                label="App"
                hint={p.connection ? `Signs every Real request in to ${host}. The key stays on the app and never shows here.` : 'An app holds the address and the sign-in once, for every tool that calls it. Mock works without one.'}
              >
                <ConnectionSelect value={p.connection} options={p.connections} loading={p.connectionsLoading} disabled={p.settingConnection} onChange={p.onConnectionChange} className="w-full sm:w-80" />
              </FormField>
              <RequestLine
                value={d.http}
                onChange={(http) => set({ http })}
                error={urlError}
                bare
                trailing={viewer ? undefined : runControls}
              />
              <p className="-mt-2 text-xs text-muted-foreground" data-testid="run-help">
                {cannotRun ? `${NO_RUN} ` : ''}{help} {realBlocked && mode === 'stub' ? realBlocked : ''} Use {'{name}'} in the address for a value the agent supplies.
              </p>
              <Tabs value={tab} onValueChange={setTab} className="gap-3">
                <TabsList>
                  <TabsTrigger value="inputs">Inputs</TabsTrigger>
                  <TabsTrigger value="headers">Headers</TabsTrigger>
                  {hasBody(d.http.method) && <TabsTrigger value="body">Body</TabsTrigger>}
                </TabsList>
                <TabsContent value="inputs">
                  <InputSchemaEditor value={d.input} onChange={(input) => set({ input })} boundArg={op.binding?.arg} errors={p.inputErrors} />
                </TabsContent>
                <TabsContent value="headers" className="flex flex-col gap-4">
                  <HeadersEditor value={d.http} onChange={(http) => set({ http })} note="Authorization comes from the connection." />
                  {(op.secrets?.length ?? 0) > 0 && (
                    <Rows testId="workbench-secrets">
                      {op.secrets!.map((s) => (
                        <Row
                          key={s.name}
                          leading={<KeyRound className="size-4 text-muted-foreground" />}
                          title={<span className="font-mono text-xs">{s.name}</span>}
                          description={s.set ? 'Set in this team' : 'Not set in this team'}
                          trailing={<Input type="password" aria-label={`${s.name} test value`} placeholder="Test value" value={secretValues[s.name] ?? ''} onChange={(e) => setSecretValues({ ...secretValues, [s.name]: e.target.value })} className="h-8 w-44 font-mono text-xs" autoComplete="off" />}
                        />
                      ))}
                    </Rows>
                  )}
                </TabsContent>
                {hasBody(d.http.method) && (
                  <TabsContent value="body">
                    <BodyEditor value={d.http} onChange={(http) => set({ http })} />
                  </TabsContent>
                )}
              </Tabs>
            </div>
          </BuilderFieldset>
          {/* Run is open to a viewer too, so the values for it, and for a viewer Mock or Real and Run, sit outside the
              builder's fieldset, which disables every control inside it. */}
          {viewer && <div className="mt-4 flex flex-wrap items-center justify-end gap-2">{runControls}</div>}
          <div className="mt-4 grid gap-3 border-t pt-4 sm:grid-cols-2" data-testid="run-values">
            <RunInputFields op={{ ...op, input: schemaOf(d.input).filter((f) => f.name) }} values={run.values} errors={run.errors} onChange={run.set} />
          </div>
        </Section>
        <Section
          title="Response"
          description="What came back, and exactly what was sent."
          actions={
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" data-testid="answer-more">
                  <Ellipsis className="size-4" /> More
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem disabled={!p.result} onSelect={() => setAnswerTab('raw')}>
                  Raw response
                </DropdownMenuItem>
                <DropdownMenuItem disabled={!p.result} onSelect={() => setAnswerTab('log')}>
                  Log
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => setExtra(extra === 'transform' ? null : 'transform')}>Transform</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setExtra(extra === 'mocks' ? null : 'mocks')}>Mock answers</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          }
        >
          {p.runError ? (
            <p className="text-sm text-destructive">{p.runError}</p>
          ) : !p.result ? (
            <p className="py-8 text-center text-sm text-muted-foreground" data-testid="response-empty">
              Run to see the answer and the request that was sent.
            </p>
          ) : (
            <ResultBody
              result={p.result}
              op={op}
              running={p.running}
              badge={MODE_BADGE[ranIn]}
              labels={{ output: 'Response', request: 'Request sent' }}
              brief
              tabs={['output', 'request', ...(answerTab === 'raw' || answerTab === 'log' ? [answerTab] : [])]}
              tab={answerTab}
              onTab={setAnswerTab}
            />
          )}
        </Section>
        {(extra === 'transform' || p.result?.transformError) && (
          <Section title="Transform" description="A Jinja2 template over the response as data. Run applies it as typed.">
            <FormField id="wb-transform" label="Template" optional error={p.result?.transformError}>
              <Textarea id="wb-transform" rows={5} value={d.transform} onChange={(e) => set({ transform: e.target.value })} className="font-mono text-xs" placeholder={'{"balance": {{ data.balance }}}'} aria-invalid={!!p.result?.transformError} />
            </FormField>
          </Section>
        )}
        {extra === 'mocks' && <MockAnswers moduleId={p.moduleId} opId={op.id} />}
      </div>
      {p.aside}
    </PageLayout>
  );
}
