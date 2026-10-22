'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { EntityPicker } from '@/components/shared/entity-picker';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { FileRef } from '@/components/shared/file-refs-field';
import { RunInputForm, withFile } from '@/components/workflows/run-input-form';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { useStartableWorkflows, useStartRun } from '@/hooks/case-queries';
import { useDefinition, useStartEngineRun, useStartWorkflow } from '@/hooks/engine-queries';
import { fileWorkflowOptions, type OptionSource, startableWorkflowOptions } from '@/hooks/options-queries';
import type { StartableWorkflow, StartRunInput } from '@/lib/types/cases';
import type { StartForm } from '@/lib/types/engine';

export type RunMode = 'live' | 'test';

type Field = StartableWorkflow['input'][number];

// An email input is the `{ sender, subject, body }` object the workflow reads.
const EMAIL_PARTS = [
  { key: 'sender', label: 'From', placeholder: 'e.g. customer@example.com' },
  { key: 'subject', label: 'Subject', placeholder: 'e.g. Charge I did not make' },
  { key: 'body', label: 'Body', placeholder: 'e.g. There is a charge on my card I do not recognise.' },
] as const;

const keyOf = (f: Field, part?: string) => (part ? `${f.name}.${part}` : f.name);

/** One screen: pick a workflow the runtime can run, fill the input its first node reads, then the run opens in Cases. */
export function StartRunDialog({
  open,
  onOpenChange,
  workflows,
  loading,
  loadError,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Workflows whose input this dialog can collect; agent-input workflows start from Chat instead. */
  workflows: StartableWorkflow[];
  loading: boolean;
  loadError?: string;
  onSubmit: (input: StartRunInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [name, setName] = React.useState('');
  const [values, setValues] = React.useState<Record<string, string>>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const wf = workflows.find((w) => w.name === name) ?? workflows[0];

  React.useEffect(() => {
    if (open) {
      setName('');
      setValues({});
      setErrors({});
      setSubmitError(null);
    }
  }, [open]);

  const set = (k: string, v: string) => (setValues((x) => ({ ...x, [k]: v })), setErrors((x) => ({ ...x, [k]: '' })));

  const submit = async () => {
    if (!wf) return;
    const errs: Record<string, string> = {};
    const input: Record<string, unknown> = {};
    for (const f of wf.input) {
      if (f.type === 'email') {
        const email = Object.fromEntries(EMAIL_PARTS.map((p) => [p.key, (values[keyOf(f, p.key)] ?? '').trim()]));
        for (const p of EMAIL_PARTS) if (f.required && !email[p.key]) errs[keyOf(f, p.key)] = `${p.label} is required.`;
        input[f.name] = email;
      } else {
        const v = (values[keyOf(f)] ?? '').trim();
        if (f.required && !v) errs[keyOf(f)] = `${f.label} is required.`;
        input[f.name] = v;
      }
    }
    setErrors(errs);
    if (Object.values(errs).some(Boolean)) return;
    const first = wf.input[0];
    const raw = first?.type === 'email' ? (values[keyOf(first, 'subject')] ?? '') : (values[first ? keyOf(first) : ''] ?? '');
    const subject = raw.trim() || wf.title;
    setSubmitError(null);
    try {
      await onSubmit({ workflowId: wf.name, subject: subject.length > 80 ? `${subject.slice(0, 79)}…` : subject, input });
      onOpenChange(false);
    } catch (err) {
      // The input stays in the fields so the person can retry.
      setSubmitError((err as Error).message);
    }
  };

  return (
    <StartRunShell
      open={open}
      onOpenChange={onOpenChange}
      title="Start a run"
      description="Runs a published workflow once on your input. The run opens in Cases when it stops."
      pending={isPending}
      canStart={!!wf}
      loadingText="Running…"
      submitTestId="start-run-submit"
      onStart={submit}
    >
      {loading ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : loadError ? (
        <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{loadError}</p>
      ) : !wf ? (
        <p className="text-sm text-muted-foreground">No workflow can be started here yet. Publish one, then start it from this dialog.</p>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {submitError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{submitError}</p>}
          <FormField id="run-workflow" label="Workflow">
            <Select value={wf.name} onValueChange={(v) => v && (setName(v), setErrors({}))}>
              <SelectTrigger id="run-workflow" className="w-full" aria-label="Workflow">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {workflows.map((w) => (
                  <SelectItem key={w.name} value={w.name}>
                    {w.title}
                    {w.latestVersion != null && <span className="text-muted-foreground tabular-nums"> · v{w.latestVersion}</span>}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {wf.input.map((f) =>
            f.type === 'email' ? (
              EMAIL_PARTS.map((p) => (
                <FormField key={keyOf(f, p.key)} id={`run-${f.name}-${p.key}`} label={p.label} error={errors[keyOf(f, p.key)] || undefined}>
                  {p.key === 'body' ? (
                    <Textarea id={`run-${f.name}-${p.key}`} rows={4} value={values[keyOf(f, p.key)] ?? ''} onChange={(e) => set(keyOf(f, p.key), e.target.value)} placeholder={p.placeholder} aria-invalid={!!errors[keyOf(f, p.key)]} />
                  ) : (
                    <Input id={`run-${f.name}-${p.key}`} value={values[keyOf(f, p.key)] ?? ''} onChange={(e) => set(keyOf(f, p.key), e.target.value)} placeholder={p.placeholder} aria-invalid={!!errors[keyOf(f, p.key)]} />
                  )}
                </FormField>
              ))
            ) : (
              <FormField key={f.name} id={`run-${f.name}`} label={f.label} optional={!f.required} error={errors[keyOf(f)] || undefined}>
                <Textarea id={`run-${f.name}`} rows={3} value={values[keyOf(f)] ?? ''} onChange={(e) => set(keyOf(f), e.target.value)} placeholder="e.g. What is the daily wire limit for a personal account?" aria-invalid={!!errors[keyOf(f)]} />
              </FormField>
            ),
          )}
        </form>
      )}
    </StartRunShell>
  );
}

/**
 * The frame both ways of starting a run share: the title and description, Cancel and Start run in the footer, and the
 * reason a start failed. A failed start keeps the dialog and what was typed, so the person can retry. Without
 * `onStart` the footer holds Cancel alone, and shows `loadingText` while `pending`.
 */
function StartRunShell({
  open,
  onOpenChange,
  title,
  description,
  pending,
  canStart = true,
  loadingText,
  submitTestId,
  startLabel = 'Start run',
  onStart,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  pending: boolean;
  canStart?: boolean;
  loadingText: string;
  submitTestId: string;
  startLabel?: string;
  onStart?: () => void;
  children: React.ReactNode;
}) {
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={title}
      description={description}
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          {(onStart || pending) && (
            <LoadingButton type="button" onClick={onStart} isLoading={pending} loadingText={loadingText} disabled={!canStart} data-testid={submitTestId}>
              {startLabel}
            </LoadingButton>
          )}
        </div>
      }
    >
      {children}
    </DialogShell>
  );
}

/**
 * The one start dialog (c-466). It draws the start form the workflow's trigger declares (`startForm`: a test email, a
 * Request trigger's input, any later kind) with the shared field widgets, and runs it live on the version that is
 * live or as a test run of the latest saved version, which is how a draft runs before review. A trigger that declares
 * no start form takes a JSON input. `file` arrives attached in the form's first file field (Files' "Start a workflow
 * with this file"). A failed start keeps the dialog and what was typed.
 */
export function StartDefinitionRunDialog({
  open,
  onOpenChange,
  workflowName,
  latestVersion,
  liveVersion,
  paused,
  startForm,
  onStart,
  onStartForm,
  file,
  fileSource,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflowName: string;
  latestVersion: number;
  /** Null before a version is approved; live runs are then refused. */
  liveVersion: number | null;
  paused: boolean;
  /** How the trigger is started by hand; null or absent for one only its source starts, which takes JSON. */
  startForm?: StartForm | null;
  /** Starts a run with a JSON input (`POST /v1/runs`), for a trigger with no start form. */
  onStart: (input: Record<string, unknown>, mode: RunMode) => Promise<void>;
  /** Starts a run from the start form's values (`POST /v1/runs/start`). */
  onStartForm?: (values: Record<string, unknown>, mode: RunMode) => Promise<void>;
  /** A file to start with, put in the form's first file field. */
  file?: FileRef;
  /** Where the file pickers' files come from; a design preview passes sample files. */
  fileSource?: OptionSource;
}) {
  const canLive = liveVersion !== null && !paused;
  const [mode, setMode] = React.useState<RunMode>(canLive ? 'live' : 'test');
  React.useEffect(() => {
    if (open) setMode(canLive ? 'live' : 'test');
  }, [open, canLive]);
  const [text, setText] = React.useState('{}');
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [error, setError] = React.useState<string | undefined>();
  const [pending, setPending] = React.useState(false);
  const schema = startForm && onStartForm ? startForm.schema : undefined;
  // Each opening starts from a clean form, with the file it was opened for already attached. Read through a ref so a
  // form object rebuilt on every render of the parent does not clear what is being typed.
  const opening = React.useRef({ file, schema });
  opening.current = { file, schema };
  React.useEffect(() => {
    if (!open) return;
    const { file: f, schema: s } = opening.current;
    setValues(f && s ? withFile(s, {}, f) : {});
    setError(undefined);
  }, [open]);

  const run = async (go: () => Promise<void>) => {
    setError(undefined);
    setPending(true);
    try {
      await go();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The run did not start');
    } finally {
      setPending(false);
    }
  };

  const submit = async () => {
    if (schema && onStartForm) {
      const missing = missingFields(schema, values);
      if (missing.length) return setError(`${missing.join(', ')} ${missing.length === 1 ? 'is' : 'are'} required.`);
      return run(() => onStartForm(values, mode));
    }
    let input: unknown;
    try {
      input = text.trim() ? JSON.parse(text) : {};
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Not valid JSON');
      return;
    }
    if (!input || typeof input !== 'object' || Array.isArray(input)) {
      setError('Input must be a JSON object');
      return;
    }
    return run(() => onStart(input as Record<string, unknown>, mode));
  };

  return (
    <StartRunShell
      open={open}
      onOpenChange={onOpenChange}
      title={schema ? `${startForm!.title}: ${workflowName}` : `Start a run of ${workflowName}`}
      description={schema ? 'It runs as its trigger would start it. Unsaved changes on the canvas are not included.' : 'Unsaved changes on the canvas are not included.'}
      pending={pending}
      loadingText="Starting…"
      submitTestId="definition-start-run-submit"
      startLabel={schema ? startForm!.action : 'Start run'}
      onStart={submit}
    >
      <RadioGroup value={mode} onValueChange={(v) => setMode(v as RunMode)} className="mb-4 gap-2" aria-label="Run mode">
        <Label htmlFor="definition-run-live" className="flex items-start gap-2 font-normal">
          <RadioGroupItem id="definition-run-live" value="live" disabled={!canLive} className="mt-0.5" />
          <span>
            <span className="font-medium">Live run</span>
            <span className="block text-xs text-muted-foreground">
              {liveVersion === null ? 'No version is live yet; publish one through Reviews first.' : paused ? `Version ${liveVersion} is live but paused.` : `On version ${liveVersion}, the live version.`}
            </span>
          </span>
        </Label>
        <Label htmlFor="definition-run-test" className="flex items-start gap-2 font-normal">
          <RadioGroupItem id="definition-run-test" value="test" className="mt-0.5" />
          <span>
            <span className="font-medium">Test run</span>
            <span className="block text-xs text-muted-foreground">On version {latestVersion}, the latest saved, whatever its stage.</span>
          </span>
        </Label>
      </RadioGroup>
      {schema ? (
        <RunInputForm schema={schema} value={values} onChange={setValues} error={error} fileSource={fileSource} />
      ) : (
        <FormField id="definition-run-input" label="Input" hint="JSON object passed to the trigger." error={error}>
          <Textarea
            id="definition-run-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            spellCheck={false}
            className="font-mono text-xs"
            aria-invalid={error ? true : undefined}
            data-testid="definition-run-input"
          />
        </FormField>
      )}
    </StartRunShell>
  );
}

/** The schema's required fields the values leave empty, by their labels. */
function missingFields(schema: Record<string, unknown>, values: Record<string, unknown>): string[] {
  const props = (schema.properties ?? {}) as Record<string, { title?: string }>;
  const empty = (v: unknown) => v === undefined || v === null || (typeof v === 'string' && !v.trim()) || (Array.isArray(v) && !v.length);
  return ((schema.required as string[] | undefined) ?? []).filter((k) => empty(values[k])).map((k) => props[k]?.title ?? k);
}

/**
 * Start one of the team's workflows: pick one from the list, searched and paged on the server (agents start from Chat,
 * and workflows only other workflows start are not offered), and that workflow's own start opens as soon as it has
 * loaded: the test email composer for an email trigger, the form its editor opens otherwise; a graph workflow of the
 * earlier engine opens the input form it has always had. With `file` (Files' "Start a workflow with this file") only
 * workflows a file can start are offered, and the file arrives attached.
 */
export function StartWorkflowRunDialog({ open, onOpenChange, file, source, fileSource }: { open: boolean; onOpenChange: (open: boolean) => void; file?: FileRef; source?: OptionSource; fileSource?: OptionSource }) {
  const router = useRouter();
  const [picked, setPicked] = React.useState<string[]>([]);
  const [chosen, setChosen] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) setPicked([]);
  }, [open]);
  // A runner definition exists for a v2 workflow; a 404 means a graph workflow of the earlier engine.
  const definition = useDefinition(chosen ?? '');
  const graph = !!chosen && (definition.error as { status?: number } | null)?.status === 404;
  const startable = useStartableWorkflows(graph);
  const { mutateAsync: startDefinition } = useStartEngineRun();
  const { mutateAsync: startByForm } = useStartWorkflow();
  const startGraph = useStartRun();
  const close = () => setChosen(null);
  const view = definition.data;
  const ready = !!chosen && (!!view || graph);
  const failed = !!chosen && definition.isError && !graph ? (definition.error?.message ?? 'The workflow did not load.') : null;
  // The picker hands over to the form once the workflow has loaded; until then it says it is opening.
  React.useEffect(() => {
    if (ready) onOpenChange(false);
  }, [ready, onOpenChange]);
  return (
    <>
      <StartRunShell
        open={open}
        onOpenChange={(o) => {
          // Cancelled while the workflow loads: no form opens afterwards.
          if (!o && !ready) setChosen(null);
          onOpenChange(o);
        }}
        title={file ? 'Start a workflow with this file' : 'Start a run'}
        description={file ? `${file.name ?? 'The file'} is attached when the workflow's start opens.` : 'Choose a workflow to open its input form.'}
        pending={!!chosen && !ready && !failed}
        loadingText="Opening…"
        submitTestId="start-run-opening"
      >
        <div className="flex flex-col gap-4">
          {failed && (
            <Alert variant="destructive">
              <AlertDescription>{failed}</AlertDescription>
            </Alert>
          )}
          <FormField id="start-run-workflow" label="Workflow" hint={file ? 'Workflows that start from an email or a form with a file; search by name.' : 'Every workflow of your team you can start; search by name.'}>
            <EntityPicker
              source={source ?? (file ? fileWorkflowOptions : startableWorkflowOptions)}
              multiple={false}
              value={picked}
              onChange={(ids) => {
                setPicked(ids);
                setChosen(ids[0] ?? null);
              }}
              addLabel="Choose a workflow"
              searchPlaceholder="Search workflows"
              testId="start-run-workflow"
            />
          </FormField>
        </div>
      </StartRunShell>
      {view && (
        <StartDefinitionRunDialog
          open={!!chosen && !!view && !open}
          onOpenChange={(o) => !o && close()}
          workflowName={view.name || view.definition.name || view.workflowId}
          latestVersion={view.version}
          liveVersion={view.liveVersion}
          paused={view.paused}
          startForm={view.startForm}
          file={file}
          fileSource={fileSource}
          onStart={async (input, mode) => {
            const run = await startDefinition({ workflowId: view.workflowId, input, mode });
            close();
            router.push(`/workflows/runs/${run.runId}`);
          }}
          onStartForm={async (values, mode) => {
            const run = await startByForm({ workflowId: view.workflowId, values, mode });
            close();
            router.push(`/workflows/runs/${run.runId}`);
          }}
        />
      )}
      <StartRunDialog
        open={graph && !open}
        onOpenChange={(o) => !o && close()}
        workflows={(startable.data ?? []).filter((w) => w.name === chosen)}
        loading={startable.isPending}
        loadError={startable.isError ? startable.error.message : undefined}
        isPending={startGraph.isPending}
        onSubmit={async (input) => {
          const { run } = await startGraph.mutateAsync(input);
          close();
          if (run) router.push(`/workflows/runs?run=${encodeURIComponent(run.id)}`);
          else toast.success('Run finished');
        }}
      />
    </>
  );
}
