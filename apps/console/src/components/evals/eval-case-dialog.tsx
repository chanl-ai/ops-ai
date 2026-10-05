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
import type { EvalCaseInput, EvalCaseOptions, EvalCheck, EvalCheckType } from '@/lib/types/evals';
import type { RunAsPrincipal } from '@/lib/types/run-as';
import { cn } from '@/lib/utils';

import { CHECK_TYPES } from './eval-meta';

const SELF = '__self';

/** Whether a check has the values its type needs. */
export function checkComplete(c: EvalCheck) {
  if (c.type === 'calls_tool' || c.type === 'not_calls_tool') return !!c.tool;
  if (c.type === 'cites') return !!c.source;
  if (c.type === 'extracts') return !!c.field?.trim() && !!c.value?.trim();
  return !!c.text?.trim();
}

function CheckRow({ check, onChange, onRemove, options, index }: { check: EvalCheck; onChange: (c: EvalCheck) => void; onRemove: () => void; options?: EvalCaseOptions; index: number }) {
  const meta = CHECK_TYPES.find((t) => t.value === check.type)!;
  const tools = options?.tools ?? [];
  const sel = (id: string, value: string | undefined, items: string[], placeholder: string, set: (v: string) => void, mono = false) => (
    <Select value={value ?? ''} onValueChange={set}>
      <SelectTrigger id={id} className={cn('w-full', mono && 'font-mono text-xs')} aria-label={placeholder}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {items.map((t) => (
          <SelectItem key={t} value={t} className={mono ? 'font-mono text-xs' : undefined}>
            {t}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
  return (
    <div className="flex flex-col gap-2 rounded-lg border p-3" data-testid="eval-check-row">
      <div className="flex items-start gap-2">
        <Select value={check.type} onValueChange={(t) => onChange({ type: t as EvalCheckType })}>
          <SelectTrigger className="w-56 shrink-0" aria-label={`Check ${index + 1} type`}>
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
        <div className="min-w-0 flex-1">
          {(check.type === 'calls_tool' || check.type === 'not_calls_tool') && sel(`chk-${index}-tool`, check.tool, tools, 'Choose a tool', (tool) => onChange({ ...check, tool }), true)}
          {check.type === 'cites' && sel(`chk-${index}-src`, check.source, options?.collections ?? [], 'Choose a knowledge base', (source) => onChange({ ...check, source }))}
          {check.type === 'extracts' && (
            <div className="grid grid-cols-2 gap-2">
              <Input aria-label="Field" value={check.field ?? ''} onChange={(e) => onChange({ ...check, field: e.target.value })} placeholder="e.g. amount" className="font-mono text-xs" />
              <Input aria-label="Value" value={check.value ?? ''} onChange={(e) => onChange({ ...check, value: e.target.value })} placeholder="e.g. 1240.18" />
            </div>
          )}
          {['reply_contains', 'reply_not_contains', 'refuses', 'rubric'].includes(check.type) && (
            <Input
              aria-label={meta.label}
              value={check.text ?? ''}
              onChange={(e) => onChange({ ...check, text: e.target.value })}
              placeholder={check.type === 'refuses' ? 'e.g. Investment advice' : check.type === 'rubric' ? 'e.g. Explains the decision in plain language' : 'e.g. callback'}
            />
          )}
        </div>
        <Button variant="ghost" size="icon" className="size-9 shrink-0" aria-label={`Remove check ${index + 1}`} onClick={onRemove}>
          <X className="size-4" />
        </Button>
      </div>
      {check.type === 'cites' && check.source && (
        <Input aria-label="Section" value={check.section ?? ''} onChange={(e) => onChange({ ...check, section: e.target.value || undefined })} placeholder="e.g. Wire Fraud Playbook §3.2 (optional)" />
      )}
      {check.type === 'calls_tool' && check.tool && (
        <div className="flex flex-col gap-1.5">
          {(check.args ?? []).map((a, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input aria-label="Argument" value={a.path} onChange={(e) => onChange({ ...check, args: check.args!.map((x, j) => (j === i ? { ...x, path: e.target.value } : x)) })} placeholder="e.g. amount" className="font-mono text-xs" />
              <span className="text-xs text-muted-foreground">equals</span>
              <Input aria-label="Expected value" value={a.equals} onChange={(e) => onChange({ ...check, args: check.args!.map((x, j) => (j === i ? { ...x, equals: e.target.value } : x)) })} placeholder="e.g. 1240.18" />
              <Button variant="ghost" size="icon" className="size-8 shrink-0" aria-label="Remove argument" onClick={() => onChange({ ...check, args: check.args!.filter((_, j) => j !== i) })}>
                <X className="size-3.5" />
              </Button>
            </div>
          ))}
          <Button variant="ghost" size="sm" className="self-start" onClick={() => onChange({ ...check, args: [...(check.args ?? []), { path: '', equals: '' }] })}>
            <Plus className="size-3.5" /> Match an argument
          </Button>
        </div>
      )}
      <p className={cn('text-xs', check.type === 'rubric' ? 'text-amber-700 dark:text-amber-400' : 'text-muted-foreground')}>{meta.hint}</p>
    </div>
  );
}

/**
 * Add a case to the agent's test set: what is sent, who it runs as, which knowledge is attached, and the checks.
 * Every check except `rubric` is scored deterministically.
 */
export function EvalCaseDialog({
  open,
  onOpenChange,
  principals,
  options,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  principals: RunAsPrincipal[];
  options?: EvalCaseOptions;
  onSubmit: (i: EvalCaseInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const blank = (): EvalCaseInput => ({ name: '', input: '', context: { collections: [] }, checks: [{ type: 'calls_tool' }] });
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
  const toggleKb = (kb: string) => setV((s) => ({ ...s, context: { ...s.context, collections: s.context.collections.includes(kb) ? s.context.collections.filter((x) => x !== kb) : [...s.context.collections, kb] } }));

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Add eval case"
      description="Runs on every save of the agent and when someone runs evals."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {errors.submit && <p className="mr-auto text-xs text-destructive">{errors.submit}</p>}
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
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="ec-runas" label="Runs as" hint="Answers and tools are limited to this person's or role's access.">
            <Select value={v.context.runAsId ?? SELF} onValueChange={(x) => setV({ ...v, context: { ...v.context, runAsId: x === SELF ? undefined : x } })}>
              <SelectTrigger id="ec-runas" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={SELF}>The agent&apos;s own access</SelectItem>
                {principals.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name} · {p.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="ec-kbs" label="Knowledge bases" optional hint="Attached for this case only.">
            <div id="ec-kbs" className="flex flex-wrap gap-1.5">
              {(options?.collections ?? []).map((kb) => {
                const on = v.context.collections.includes(kb);
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
              options={options}
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
