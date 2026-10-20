'use client';

import * as React from 'react';
import { Sparkles } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import type { OptionInput, ReviewOption } from '@/lib/types/domain';
import { EntityPicker } from '@/components/shared/entity-picker';
import { peopleOptions } from '@/hooks/options-queries';

const label = (name: string) => name.replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase());
const fieldId = (option: string, input: string) => `opt-${option}-${input}`;
const numeric = (i: OptionInput) => i.type === 'number' || i.type === 'integer';

/** The values a form opens with: each input's declared default, blank when it has none. */
const defaults = (options: ReviewOption[]) => Object.fromEntries(options.flatMap((o) => (o.inputs ?? []).map((i) => [fieldId(o.name, i.name), i.default == null ? (i.type === 'boolean' ? false : '') : i.default])));

/** The reviewer's value as the API expects it: a number for numeric inputs, else as typed. */
function coerce(input: OptionInput, raw: unknown): unknown {
  if (input.type === 'boolean') return raw === true;
  if (numeric(input)) return raw === '' || raw == null ? undefined : Number(raw);
  return raw === '' ? undefined : raw;
}

/** The first rule the value breaks, as the API would say it, so a refusal is caught before the request. */
function problem(input: OptionInput, value: unknown): string | null {
  if (value === undefined) return input.required ? `${label(input.name)} is required.` : null;
  if (numeric(input)) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return `${label(input.name)} must be a number.`;
    if (input.type === 'integer' && !Number.isInteger(value)) return `${label(input.name)} must be a whole number.`;
    if (input.minimum != null && value < input.minimum) return `${label(input.name)} must be at least ${input.minimum}.`;
    if (input.maximum != null && value > input.maximum) return `${label(input.name)} must be at most ${input.maximum}.`;
  }
  return null;
}

/**
 * Decision form for a step that offers options. Each option is its own button and runs the call the step declares
 * for it; the inputs an option declares (from its operation's schema) render as fields, prefilled with the values
 * the step proposed, and go to the API as `inputs`, which validates them against the same declaration. An option
 * whose policy asks for a step-up says so on its button.
 */
export function OptionDecisionForm({
  reviewId,
  options,
  pending,
  onDecide,
  layout = 'sheet',
  blocked,
  suggested,
}: {
  /** The option an AI assist suggests, by name: its button is marked, and it is never chosen for the person. */
  suggested?: string;
  reviewId: string;
  /** Why an option waits ("confirm 2 key fields first"), by its name; its button says so and stays off. */
  blocked?: Record<string, string | undefined>;
  /** `sheet` sticks to the bottom of a side sheet; `footer` is one row of a page grid: the focused option's consequence
   * and the buttons, with an option's inputs opening a row above only once that option is chosen. */
  layout?: 'sheet' | 'footer';
  options: ReviewOption[];
  /** The option being sent, while the request is in flight. */
  pending: string | null;
  onDecide: (option: ReviewOption, input: { inputs: Record<string, unknown>; reason: string }) => void;
}) {
  // A refetch hands over a new array of the same options; only another review or other options start the form over,
  // so a chosen option, its typed inputs and its reason survive a re-render between the two presses.
  const optionsKey = options.map((o) => o.name).join('|');
  const [values, setValues] = React.useState<Record<string, unknown>>(() => defaults(options));
  const [reason, setReason] = React.useState('');
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  React.useEffect(() => {
    setValues(defaults(options));
    setReason('');
    setErrors({});
  }, [reviewId, optionsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (id: string, v: unknown) => {
    setValues((prev) => ({ ...prev, [id]: v }));
    setErrors((prev) => (prev[id] ? Object.fromEntries(Object.entries(prev).filter(([k]) => k !== id)) : prev));
  };
  const submit = (option: ReviewOption) => {
    const inputs: Record<string, unknown> = {};
    const found: Record<string, string> = {};
    for (const input of option.inputs ?? []) {
      const id = fieldId(option.name, input.name);
      const value = coerce(input, values[id]);
      const bad = problem(input, value);
      if (bad) found[id] = bad;
      else if (value !== undefined) inputs[input.name] = value;
    }
    setErrors(found);
    if (Object.keys(found).length) return;
    onDecide(option, { inputs, reason: reason.trim() });
  };
  const withInputs = options.filter((o) => o.inputs?.length);
  const inputRows = (list: ReviewOption[]) =>
    list.map((option) => (
        <div key={option.name} className="flex flex-col gap-2" data-testid={`option-inputs-${option.name}`}>
          {withInputs.length > 1 && <Label className="text-xs text-muted-foreground">{label(option.name)}</Label>}
          {(option.inputs ?? []).map((input) => {
            const id = fieldId(option.name, input.name);
            const value = values[id];
            if (input.type === 'boolean')
              return (
                <div key={id} className="flex items-center justify-between gap-4">
                  <Label htmlFor={id}>{label(input.name)}</Label>
                  <Switch id={id} checked={value === true} onCheckedChange={(v) => set(id, v)} />
                </div>
              );
            const hint = [input.minimum != null && `at least ${input.minimum}`, input.maximum != null && `at most ${input.maximum}`].filter(Boolean).join(', ');
            return (
              <FormField key={id} id={id} label={input.label ?? `${label(input.name)} to ${option.name}`} optional={!input.required} hint={input.format === 'person' ? 'Empty sends it back to the team queue.' : hint || undefined} error={errors[id]}>
                {input.format === 'person' ? (
                  <EntityPicker
                    source={peopleOptions}
                    multiple={false}
                    value={value ? [String(value)] : []}
                    onChange={(next) => set(id, next[0] ?? '')}
                    addLabel="Pick a person"
                    searchPlaceholder="Search the team's people…"
                    emptyText="No one in the team matches."
                    testId={`option-person-${option.name}-${input.name}`}
                  />
                ) : input.enum?.length ? (
                  <Select value={String(value ?? '')} onValueChange={(v) => set(id, numeric(input) ? Number(v) : v)}>
                    <SelectTrigger id={id} className="w-full bg-card">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {input.enum.map((o) => (
                        <SelectItem key={String(o)} value={String(o)}>
                          {String(o)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input id={id} inputMode={numeric(input) ? 'decimal' : undefined} value={String(value ?? '')} onChange={(e) => set(id, e.target.value)} aria-invalid={!!errors[id]} className="bg-card" />
                )}
              </FormField>
            );
          })}
        </div>
          ));
  const [focused, setFocused] = React.useState(options[0]?.name);
  const [armed, setArmed] = React.useState<string | null>(null);
  React.useEffect(() => {
    setFocused(options[0]?.name);
    setArmed(null);
  }, [reviewId, optionsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  if (layout === 'footer') {
    const shown = options.find((o) => o.name === (armed ?? focused)) ?? options[0];
    const armedOption = withInputs.find((o) => o.name === armed);
    // An option that asks for inputs or a reason shows them first; the second press sends it.
    const asks = (o: ReviewOption) => !!o.inputs?.length || o.reason === 'required';
    const armedReason = options.find((o) => o.name === armed && o.reason === 'required');
    const send = (o: ReviewOption) => {
      if (o.reason === 'required' && !reason.trim()) return setErrors((e) => ({ ...e, reason: `Add a reason to ${(o.label ?? label(o.name)).toLowerCase()}.` }));
      submit(o);
    };
    return (
      <div className="flex flex-col gap-2 border-t bg-background px-4 py-3 lg:px-6" data-testid="option-decision-form" data-layout="footer">
        {armedOption && inputRows([armedOption])}
        {armedReason && (
          <FormField id="option-reason-required" label="Reason" error={errors.reason}>
            <Input id="option-reason-required" value={reason} onChange={(e) => (setReason(e.target.value), setErrors((x) => ({ ...x, reason: '' })))} autoFocus className="bg-card" data-testid="option-reason" />
          </FormField>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {shown?.consequence && (
            // Beside the buttons from sm up, however long: basis-0 lets it shrink and wrap instead of taking its own line.
            <p className="min-w-0 basis-full text-sm sm:flex-1 sm:basis-0" data-testid="review-consequence">
              {shown.label ?? label(shown.name)}: {shown.consequence}
            </p>
          )}
          <div className="ml-auto flex gap-2 max-sm:w-full max-sm:*:flex-1">
            {options.map((option, i) => (
              <LoadingButton
                key={option.name}
                size="sm"
                variant={(option.tone ? option.tone === 'primary' : i === 0) ? 'default' : 'outline'}
                className={option.tone === 'destructive' ? 'text-destructive' : undefined}
                isLoading={pending === option.name}
                disabled={!!pending || !!blocked?.[option.name]}
                onMouseEnter={() => setFocused(option.name)}
                onFocus={() => setFocused(option.name)}
                onClick={() => (asks(option) && armed !== option.name ? setArmed(option.name) : send(option))}
                data-testid={`decide-${option.name}`}
                data-suggested={suggested === option.name || undefined}
              >
                {suggested === option.name && <Sparkles className="size-3.5" aria-label="Suggested by AI" />}
                {option.label ?? label(option.name)}
                {blocked?.[option.name] ? ` · ${blocked[option.name]}` : ''}
                {option.stepUp && <span className="text-[10px] opacity-70"> · confirm it's you</span>}
              </LoadingButton>
            ))}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="sticky bottom-0 -mx-6 -mb-4 flex flex-col gap-3 border-t bg-background px-6 py-4 shadow-[0_-4px_12px_-8px_rgb(0_0_0/0.15)]" data-testid="option-decision-form">
      {inputRows(withInputs)}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="option-reason">
          Reason <span className="font-normal text-muted-foreground">(optional)</span>
        </Label>
        <Textarea id="option-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Amount matches the statement; customer confirmed by phone" className="min-h-16 resize-none bg-card" />
        <p className="text-xs text-muted-foreground">Recorded on the decision and in the audit log.</p>
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {options.map((option, i) => (
          <LoadingButton key={option.name} size="sm" variant={i === 0 ? 'default' : 'outline'} isLoading={pending === option.name} disabled={!!pending} onClick={() => submit(option)} data-testid={`decide-${option.name}`} title={option.stepUp ? 'Asks you to confirm it is you' : undefined}>
            {option.label ?? label(option.name)}
            {option.stepUp && <span className="text-[10px] opacity-70"> · confirm it's you</span>}
          </LoadingButton>
        ))}
      </div>
    </div>
  );
}
