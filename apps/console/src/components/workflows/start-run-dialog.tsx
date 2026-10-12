'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import type { StartableWorkflow, StartRunInput } from '@/lib/types/cases';

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
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Start a run"
      description="Runs a published workflow once on your input. The run opens in Cases when it stops."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={isPending} loadingText="Running…" disabled={!wf} data-testid="start-run-submit">
            Start run
          </LoadingButton>
        </div>
      }
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
    </DialogShell>
  );
}
