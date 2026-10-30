'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';

import { DialogShell } from '@/components/shared/dialog-shell';
import { EntityPicker } from '@/components/shared/entity-picker';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import type { FileRef } from '@/components/shared/file-refs-field';
import { RunInputForm, withFile } from '@/components/workflows/run-input-form';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { type CheckedFile, StartFromFile } from '@/components/workflows/start-from-file';
import { useStartBatch } from '@/hooks/batch-queries';
import { useDefinition, useStartEngineRun, useStartWorkflow } from '@/hooks/engine-queries';
import { fileWorkflowOptions, type OptionSource, startableWorkflowOptions } from '@/hooks/options-queries';
import { useHostedForms } from '@/hooks/use-switches';
import type { StartForm } from '@/lib/types/engine';
import { plural } from '@/lib/format';

export type RunMode = 'live' | 'test';

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
 * with this file"). A failed start keeps the dialog and what was typed. With hosted forms on, a form trigger also
 * offers Start from a file: one run per row of a CSV or Excel file, followed on the batch's page (c-535).
 */
export function StartDefinitionRunDialog({
  open,
  onOpenChange,
  workflowId,
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
  /** The workflow a file's rows start; without it the dialog offers no Start from a file. */
  workflowId?: string;
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
  const router = useRouter();
  const hostedForms = useHostedForms();
  const inputs = (schema?.properties ?? {}) as Record<string, { title?: string }>;
  // A file's columns can only name a form trigger's inputs.
  const fromFile = hostedForms && !!workflowId && startForm?.kind === 'form' && Object.keys(inputs).length > 0;
  const [tab, setTab] = React.useState<'form' | 'file'>('form');
  const [checked, setChecked] = React.useState<CheckedFile | null>(null);
  const [batchError, setBatchError] = React.useState<string | undefined>();
  const { mutateAsync: startBatch } = useStartBatch(workflowId ?? '');
  // Each opening starts from a clean form, with the file it was opened for already attached. Read through a ref so a
  // form object rebuilt on every render of the parent does not clear what is being typed.
  const opening = React.useRef({ file, schema });
  opening.current = { file, schema };
  React.useEffect(() => {
    if (!open) return;
    const { file: f, schema: s } = opening.current;
    setValues(f && s ? withFile(s, {}, f) : {});
    setError(undefined);
    setTab('form');
    setChecked(null);
    setBatchError(undefined);
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

  const startFile = async () => {
    if (!checked) return;
    setBatchError(undefined);
    setPending(true);
    try {
      const batch = await startBatch({ fileId: checked.fileId, mode });
      onOpenChange(false);
      router.push(`/workflows/batches/${encodeURIComponent(batch.id)}`);
    } catch (e) {
      setBatchError(e instanceof Error ? e.message : 'The runs did not start');
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
      {...(fromFile && tab === 'file'
        ? { submitTestId: 'batch-start', startLabel: checked ? `Start ${plural(checked.dry.rows, 'run')}` : 'Start runs', canStart: !!checked, onStart: startFile }
        : { submitTestId: 'definition-start-run-submit', startLabel: schema ? startForm!.action : 'Start run', onStart: submit })}
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
      {schema && fromFile ? (
        <Tabs value={tab} onValueChange={(v) => setTab(v as 'form' | 'file')} className="min-w-0 gap-4">
          <TabsList aria-label="How to start">
            <TabsTrigger value="form">Fill the form</TabsTrigger>
            <TabsTrigger value="file" data-testid="start-from-file">
              Start from a file
            </TabsTrigger>
          </TabsList>
          <TabsContent value="form" className="min-w-0">
            <RunInputForm schema={schema} value={values} onChange={setValues} error={error} fileSource={fileSource} />
          </TabsContent>
          <TabsContent value="file" className="min-w-0">
            <StartFromFile workflowId={workflowId!} mode={mode} inputs={inputs} onChecked={setChecked} startError={batchError} />
          </TabsContent>
        </Tabs>
      ) : schema ? (
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
 * loaded: the test email composer for an email trigger, the form its editor opens otherwise. With `file` (Files' "Start a workflow with this file") only
 * workflows a file can start are offered, and the file arrives attached.
 */
export function StartWorkflowRunDialog({ open, onOpenChange, file, source, fileSource }: { open: boolean; onOpenChange: (open: boolean) => void; file?: FileRef; source?: OptionSource; fileSource?: OptionSource }) {
  const router = useRouter();
  const [picked, setPicked] = React.useState<string[]>([]);
  const [chosen, setChosen] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) setPicked([]);
  }, [open]);
  const definition = useDefinition(chosen ?? '');
  const { mutateAsync: startDefinition } = useStartEngineRun();
  const { mutateAsync: startByForm } = useStartWorkflow();
  const close = () => setChosen(null);
  const view = definition.data;
  const ready = !!chosen && !!view;
  // A workflow the runner does not hold was built on the earlier engine, which the console no longer starts.
  const gone = (definition.error as { status?: number } | null)?.status === 404;
  const failed = !!chosen && definition.isError ? (gone ? 'That workflow is no longer available.' : (definition.error?.message ?? 'The workflow did not load.')) : null;
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
          workflowId={view.workflowId}
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
    </>
  );
}
