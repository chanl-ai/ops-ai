'use client';

import * as React from 'react';
import { Plus } from 'lucide-react';

import { CheckRow, checkComplete } from '@/components/evals/eval-case-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { SkillTestCaseInput } from '@/lib/types/skills';

/**
 * Add or edit one skill test case: the input and the checks, which are the agent eval checks (expected tool calls,
 * must cite, must not say). Used on the skill page and in the generate dialog's Tests step.
 */
export function SkillTestDialog({
  open,
  onOpenChange,
  initial,
  tools,
  knowledgeBases,
  onSubmit,
  isPending = false,
  modal,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  /** Editing when set. */
  initial?: SkillTestCaseInput;
  tools: string[];
  knowledgeBases: string[];
  onSubmit: (i: SkillTestCaseInput) => Promise<unknown> | void;
  isPending?: boolean;
  modal?: boolean;
}) {
  const blank = (): SkillTestCaseInput => ({ name: '', input: '', checks: [{ type: 'calls_tool' }] });
  const [v, setV] = React.useState<SkillTestCaseInput>(blank);
  const [errors, setErrors] = React.useState<{ name?: string; input?: string; checks?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) {
      setV(initial ? structuredClone(initial) : blank());
      setErrors({});
    }
  }, [open, initial]);

  const submit = async () => {
    const e = {
      name: v.name.trim() ? undefined : 'Name the case so a failure is recognisable.',
      input: v.input.trim() ? undefined : 'Add the message this case sends.',
      checks: !v.checks.length ? 'Add at least one check.' : v.checks.some((c) => !checkComplete(c)) ? 'Fill in every check, or remove the empty ones.' : undefined,
    };
    setErrors(e);
    if (e.name || e.input || e.checks) return;
    try {
      await onSubmit(v);
      onOpenChange(false);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      modal={modal}
      size="lg"
      title={initial ? 'Edit test case' : 'Add test case'}
      description="Runs when someone runs the skill’s tests, and before a version can go to review."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {errors.submit && <p className="mr-auto text-xs text-destructive">{errors.submit}</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={isPending} data-testid="skill-test-submit">
            {initial ? 'Save case' : 'Add case'}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="st-name" label="Name" error={errors.name}>
          <Input id="st-name" aria-invalid={!!errors.name} value={v.name} onChange={(e) => (setV({ ...v, name: e.target.value }), setErrors({ ...errors, name: undefined }))} placeholder="e.g. Job loss on a mortgage is triaged" />
        </FormField>
        <FormField id="st-input" label="Input" error={errors.input} hint="What a customer or colleague sends. The skill must be chosen for it.">
          <Textarea id="st-input" aria-invalid={!!errors.input} value={v.input} onChange={(e) => (setV({ ...v, input: e.target.value }), setErrors({ ...errors, input: undefined }))} className="min-h-20" placeholder="e.g. I was laid off and can’t make next month’s payment." />
        </FormField>
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Checks</span>
            <Button variant="outline" size="sm" onClick={() => (setV({ ...v, checks: [...v.checks, { type: 'reply_contains' }] }), setErrors({ ...errors, checks: undefined }))}>
              <Plus className="size-3.5" /> Add check
            </Button>
          </div>
          {v.checks.map((c, i) => (
            <CheckRow
              key={i}
              index={i}
              check={c}
              options={{ tools, collections: knowledgeBases, documents: [] }}
              onChange={(next) => (setV({ ...v, checks: v.checks.map((x, j) => (j === i ? next : x)) }), setErrors({ ...errors, checks: undefined }))}
              onRemove={() => setV({ ...v, checks: v.checks.filter((_, j) => j !== i) })}
            />
          ))}
          {errors.checks && <p className="text-xs text-destructive">{errors.checks}</p>}
        </div>
      </div>
    </DialogShell>
  );
}
