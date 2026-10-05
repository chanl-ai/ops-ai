'use client';

import * as React from 'react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import type { Lookups } from '@/lib/api';
import type { GatePolicy, GatePolicyInput } from '@/lib/types/domain';

const EMPTY: GatePolicyInput = { name: '', workflowId: '', condition: '', reviewers: '', sla: '1 h', onTimeout: '', fourEyes: false };

type Errors = Partial<Record<keyof GatePolicyInput, string>>;

function validate(v: GatePolicyInput): Errors {
  const e: Errors = {};
  if (!v.name.trim()) e.name = 'Name the gate so reviewers know why a run paused.';
  if (!v.workflowId) e.workflowId = 'Choose the workflow this gate belongs to.';
  if (!v.condition.trim()) e.condition = 'Add the condition that pauses a run.';
  if (!v.reviewers) e.reviewers = 'Choose who reviews paused runs.';
  if (!v.onTimeout.trim()) e.onTimeout = 'Say what happens if nobody decides in time.';
  return e;
}

/** Create or edit one gate policy. Seven fields, so it is a single `md` dialog rather than a wizard. */
export function GatePolicyDialog({
  open,
  onOpenChange,
  policy,
  lookups,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  policy?: GatePolicy | null;
  lookups?: Lookups;
  onSubmit: (input: GatePolicyInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [values, setValues] = React.useState<GatePolicyInput>(EMPTY);
  const [errors, setErrors] = React.useState<Errors>({});
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const [confirming, setConfirming] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setValues(
      policy
        ? { name: policy.name, workflowId: policy.workflowId, condition: policy.condition, reviewers: policy.reviewers, sla: policy.sla, onTimeout: policy.onTimeout, fourEyes: policy.fourEyes }
        : EMPTY,
    );
    setErrors({});
    setSubmitError(null);
    setConfirming(false);
  }, [open, policy]);

  const set = <K extends keyof GatePolicyInput>(k: K, v: GatePolicyInput[K]) => {
    setConfirming(false);
    setValues((s) => ({ ...s, [k]: v }));
    setErrors((e) => ({ ...e, [k]: undefined }));
  };

  const submit = async () => {
    const e = validate(values);
    setErrors(e);
    if (Object.keys(e).length) return;
    // Gates decide which runs pause before acting; an edit changes that for every new run, so it takes a second click.
    if (policy && !confirming) return setConfirming(true);
    try {
      await onSubmit(values);
      onOpenChange(false);
    } catch (err) {
      setSubmitError((err as Error).message);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={policy ? 'Edit gate' : 'New gate'}
      description="Runs that match the condition pause until a reviewer decides."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={isPending} loadingText="Saving…" variant={confirming ? 'destructive' : 'default'}>
            {policy ? (confirming ? 'Apply to new runs' : 'Save gate') : 'Create gate'}
          </LoadingButton>
        </div>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        {submitError && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{submitError}</p>}
        {confirming && (
          <p className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200" role="alert">
            From the next run, {values.reviewers || 'the reviewer group'} reviews runs where <code className="font-mono text-xs">{values.condition}</code>. Runs already paused keep their current gate.
          </p>
        )}
        <FormField id="gate-name" label="Name" error={errors.name}>
          <Input id="gate-name" value={values.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Large transfer to a new payee" aria-invalid={!!errors.name} />
        </FormField>
        <FormField id="gate-workflow" label="Workflow" error={errors.workflowId}>
          <Select value={values.workflowId} onValueChange={(v) => set('workflowId', v)}>
            <SelectTrigger id="gate-workflow" className="w-full" aria-invalid={!!errors.workflowId}>
              <SelectValue placeholder="Choose a workflow" />
            </SelectTrigger>
            <SelectContent>
              {lookups?.workflows.map((w) => (
                <SelectItem key={w.id} value={w.id}>
                  {w.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="gate-condition" label="Pause the run when" error={errors.condition} hint="Uses run fields, e.g. amount, payee.age, agent.confidence.">
          <Textarea
            id="gate-condition"
            value={values.condition}
            onChange={(e) => set('condition', e.target.value)}
            placeholder="amount > 50,000 AND payee.age < 72h"
            className="min-h-16 font-mono text-xs"
            aria-invalid={!!errors.condition}
          />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="gate-reviewers" label="Reviewer group" error={errors.reviewers}>
            <Select value={values.reviewers} onValueChange={(v) => set('reviewers', v)}>
              <SelectTrigger id="gate-reviewers" className="w-full" aria-invalid={!!errors.reviewers}>
                <SelectValue placeholder="Choose a group" />
              </SelectTrigger>
              <SelectContent>
                {lookups?.reviewerGroups.map((g) => (
                  <SelectItem key={g} value={g}>
                    {g}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="gate-sla" label="Decision SLA">
            <Select value={values.sla} onValueChange={(v) => set('sla', v)}>
              <SelectTrigger id="gate-sla" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {lookups?.slaOptions.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <FormField id="gate-timeout" label="If nobody decides in time" error={errors.onTimeout}>
          <Input id="gate-timeout" value={values.onTimeout} onChange={(e) => set('onTimeout', e.target.value)} placeholder="e.g. Escalate to a senior reviewer" aria-invalid={!!errors.onTimeout} />
        </FormField>
        <label htmlFor="gate-four-eyes" className="flex items-start justify-between gap-4 rounded-lg border p-3">
          <span>
            <span className="block text-sm font-medium">Require two approvers</span>
            <span className="block text-xs text-muted-foreground">Both from the reviewer group. Use for anything that moves money.</span>
          </span>
          <Switch id="gate-four-eyes" checked={values.fourEyes} onCheckedChange={(v) => set('fourEyes', v)} />
        </label>
      </form>
    </DialogShell>
  );
}
