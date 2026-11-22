'use client';

import * as React from 'react';
import { Plus, X } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type { EvalCaseInput, EvalCheck, EvalCheckType } from '@/lib/types/evals';

import { CHECK_TYPES } from './eval-meta';


/** Whether a check has the values its type needs; a judge without its rubric is refused by the service too. */
export function checkComplete(c: EvalCheck) {
  if (c.type === 'calls_tool') return !!c.tool;
  if (c.type === 'judge') return !!c.rubric?.trim();
  return !!c.text?.trim();
}

/** One check's editor: its type and the one value that type needs. */
function CheckRow({ check, onChange, onRemove, tools, index }: { check: EvalCheck; onChange: (c: EvalCheck) => void; onRemove: () => void; tools: string[]; index: number }) {
  const meta = CHECK_TYPES.find((t) => t.value === check.type)!;
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3" data-testid="eval-check-row">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <Select value={check.type} onValueChange={(t) => onChange({ type: t as EvalCheckType })}>
          <SelectTrigger className="w-full sm:w-56 sm:shrink-0" aria-label={`Check ${index + 1} type`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CHECK_TYPES.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="min-w-0 sm:flex-1">
          {check.type === 'calls_tool' && (
            <Select value={check.tool ?? ''} onValueChange={(tool) => onChange({ ...check, tool })}>
              <SelectTrigger className="w-full font-mono text-xs" aria-label="Choose a tool">
                <SelectValue placeholder="Choose a tool" />
              </SelectTrigger>
              <SelectContent>
                {tools.map((t) => (
                  <SelectItem key={t} value={t} className="font-mono text-xs">
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {(check.type === 'reply_contains' || check.type === 'refuses') && (
            <Input aria-label={meta.label} value={check.text ?? ''} onChange={(e) => onChange({ ...check, text: e.target.value })} placeholder={check.type === 'refuses' ? 'e.g. Investment advice' : 'e.g. callback'} />
          )}
          {check.type === 'judge' && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`chk-${index}-rubric`} className="text-xs font-medium">
                What a good reply does
              </label>
              <Textarea id={`chk-${index}-rubric`} value={check.rubric ?? ''} onChange={(e) => onChange({ ...check, rubric: e.target.value })} className="min-h-16" placeholder="e.g. Explains the decision in plain language" />
            </div>
          )}
        </div>
        <Button variant="ghost" size="icon" className="size-9 shrink-0 self-end sm:self-auto" aria-label={`Remove check ${index + 1}`} onClick={onRemove}>
          <X className="size-4" />
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{meta.hint}</p>
    </div>
  );
}

/**
 * Add a case to the agent's saved cases: what is sent, which knowledge is attached, and the checks. The tools and
 * knowledge bases offered are the ones the agent already holds. A judge check is graded by a model, so a run with one
 * costs more.
 */
export function EvalCaseDialog({
  open,
  onOpenChange,
  tools,
  collections,
  onSubmit,
  isPending,
  seed,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  tools: string[];
  collections: string[];
  onSubmit: (i: EvalCaseInput) => Promise<unknown>;
  isPending: boolean;
  /** What a new case starts from, such as a success check offered as its rubric. */
  seed?: Partial<EvalCaseInput>;
}) {
  const blank = (): EvalCaseInput => ({ name: '', input: '', collections: [], checks: [{ type: 'calls_tool' }], ...seed });
  const [v, setV] = React.useState<EvalCaseInput>(blank);
  const [errors, setErrors] = React.useState<{ name?: string; input?: string; checks?: string; submit?: string }>({});
  React.useEffect(() => {
    if (open) {
      setV(blank());
      setErrors({});
    }
  }, [open]);

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
  const toggleKb = (kb: string) => setV((s) => ({ ...s, collections: s.collections.includes(kb) ? s.collections.filter((x) => x !== kb) : [...s.collections, kb] }));

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Add eval case"
      description="Runs when someone presses Run evals or runs opsai agents eval."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {errors.submit && <p className="mr-auto text-xs text-destructive-text">{errors.submit}</p>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={isPending}>
            Add case
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="ec-name" label="Name" error={errors.name}>
          <Input id="ec-name" aria-invalid={!!errors.name} value={v.name} onChange={(e) => (setV({ ...v, name: e.target.value }), setErrors({ ...errors, name: undefined }))} placeholder="e.g. New payee over $50,000 is held" />
        </FormField>
        <FormField id="ec-input" label="Input" error={errors.input} hint="What a customer or upstream system sends.">
          <Textarea id="ec-input" aria-invalid={!!errors.input} value={v.input} onChange={(e) => (setV({ ...v, input: e.target.value }), setErrors({ ...errors, input: undefined }))} className="min-h-20" placeholder="e.g. I never received the order and the merchant stopped answering." />
        </FormField>
        <div className="grid gap-4">
          <FormField id="ec-kbs" label="Knowledge bases" optional hint="Attached for this case only.">
            <div id="ec-kbs" className="flex flex-wrap gap-1.5">
              {collections.map((kb) => {
                const on = v.collections.includes(kb);
                return (
                  <button key={kb} type="button" onClick={() => toggleKb(kb)} aria-pressed={on} className="rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                    <Badge variant={on ? 'default' : 'outline'} className="cursor-pointer font-normal">
                      {kb}
                    </Badge>
                  </button>
                );
              })}
            </div>
          </FormField>
        </div>
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
              tools={tools}
              onChange={(next) => (setV({ ...v, checks: v.checks.map((x, j) => (j === i ? next : x)) }), setErrors({ ...errors, checks: undefined }))}
              onRemove={() => setV({ ...v, checks: v.checks.filter((_, j) => j !== i) })}
            />
          ))}
          {errors.checks && <p className="text-xs text-destructive-text">{errors.checks}</p>}
        </div>
      </div>
    </DialogShell>
  );
}
