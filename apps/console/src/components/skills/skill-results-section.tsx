'use client';

import * as React from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { Plus, X } from 'lucide-react';
import { Controller, useFieldArray, useForm } from 'react-hook-form';
import { z } from 'zod';

import { FormField } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import type { SkillReturnField } from '@/lib/types/skills';

const EXIT_NAME = /^[a-z][a-z0-9_]{0,31}$/;
const RESULT_NAME = /^[a-z][a-z0-9_]{0,63}$/;
const NAME_HELP = 'Lower-case letters, digits and underscores, starting with a letter, e.g. needs_review.';

/** The limits are the service's (a skill's program): 8 exits, 12 results, 8 lines, 300 characters each. */
export const skillEndingSchema = z.object({
  exits: z
    .array(z.object({ name: z.string().regex(EXIT_NAME, NAME_HELP).refine((n) => n !== 'done' && n !== 'failed', 'Every skill already ends as done or failed.'), meaning: z.string().trim().min(1, 'Say what this ending means.').max(300, 'Keep it under 300 characters.') }))
    .max(8, 'A skill has at most 8 endings of its own.')
    .refine((rows) => new Set(rows.map((r) => r.name)).size === rows.length, 'Each ending needs its own name.'),
  returns: z
    .array(z.object({ name: z.string().regex(RESULT_NAME, NAME_HELP).refine((n) => n !== 'exit', 'exit is taken: it names how the skill ended.'), type: z.enum(['text', 'number', 'yes_no']), required: z.boolean(), description: z.string().max(300, 'Keep it under 300 characters.') }))
    .max(12, 'A skill hands back at most 12 results.'),
  success: z.array(z.object({ line: z.string().trim().min(1, 'Write the check, or remove the line.').max(300, 'Keep it under 300 characters.') })).max(8, 'At most 8 lines.'),
});
export type SkillEnding = z.infer<typeof skillEndingSchema>;

export interface SkillEndingValue {
  exit: Record<string, string>;
  returns: SkillReturnField[];
  success: string[];
}

const toForm = (v: SkillEndingValue): SkillEnding => ({ exits: Object.entries(v.exit).map(([name, meaning]) => ({ name, meaning })), returns: v.returns, success: v.success.map((line) => ({ line })) });
const fromForm = (f: SkillEnding): SkillEndingValue => ({ exit: Object.fromEntries(f.exits.map((e) => [e.name, e.meaning.trim()])), returns: f.returns, success: f.success.map((s) => s.line.trim()) });

const TYPES: { value: SkillReturnField['type']; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'yes_no', label: 'Yes or no' },
];

/**
 * How a skill with steps may end, what it hands back and what says it went well. The values are
 * passed up on every valid change and saved with the rest of the draft; `onValidity` tells the page to hold the save
 * while a field is wrong.
 */
export function SkillResultsSection({ value, onChange, onValidity, disabled }: { value: SkillEndingValue; onChange: (next: SkillEndingValue) => void; onValidity: (valid: boolean) => void; disabled?: boolean }) {
  const form = useForm<SkillEnding>({ resolver: zodResolver(skillEndingSchema), defaultValues: toForm(value), mode: 'onChange' });
  const { control, register, formState, watch } = form;
  const exits = useFieldArray({ control, name: 'exits' });
  const returns = useFieldArray({ control, name: 'returns' });
  const success = useFieldArray({ control, name: 'success' });
  const errors = formState.errors;

  React.useEffect(() => {
    const sub = watch((values) => {
      const parsed = skillEndingSchema.safeParse(values);
      onValidity(parsed.success);
      if (parsed.success) onChange(fromForm(parsed.data));
    });
    return () => sub.unsubscribe();
  }, [watch, onChange, onValidity]);

  return (
    <SettingsSection title="Endings and results" description="These apply to a skill with steps. Every skill ends as done or failed; add an ending when a step should stop the skill another way.">
      <fieldset disabled={disabled} className="flex flex-col gap-6" data-testid="skill-results-section">
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Endings</span>
          {exits.fields.map((f, i) => (
            <div key={f.id} className="flex flex-col gap-2 sm:flex-row sm:items-start">
              <FormField id={`sk-exit-name-${i}`} label="Name" className="sm:w-48" error={errors.exits?.[i]?.name?.message}>
                <Input id={`sk-exit-name-${i}`} className="bg-card font-mono text-xs" aria-invalid={!!errors.exits?.[i]?.name} {...register(`exits.${i}.name`)} />
              </FormField>
              <FormField id={`sk-exit-meaning-${i}`} label="What it means" className="flex-1" error={errors.exits?.[i]?.meaning?.message}>
                <Input id={`sk-exit-meaning-${i}`} className="bg-card" aria-invalid={!!errors.exits?.[i]?.meaning} {...register(`exits.${i}.meaning`)} />
              </FormField>
              <Button type="button" variant="ghost" size="icon" className="sm:mt-6" aria-label={`Remove ending ${i + 1}`} onClick={() => exits.remove(i)}>
                <X className="size-4" />
              </Button>
            </div>
          ))}
          {errors.exits?.root?.message && <p className="text-sm text-destructive-text">{errors.exits.root.message}</p>}
          <Button type="button" variant="outline" size="sm" className="self-start" disabled={exits.fields.length >= 8} onClick={() => exits.append({ name: '', meaning: '' })} data-testid="add-skill-exit">
            <Plus className="size-4" /> Add an ending
          </Button>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Results</span>
          {returns.fields.map((f, i) => (
            <div key={f.id} className="flex flex-col gap-2 sm:flex-row sm:items-start">
              <FormField id={`sk-ret-name-${i}`} label="Name" className="sm:w-48" error={errors.returns?.[i]?.name?.message}>
                <Input id={`sk-ret-name-${i}`} className="bg-card font-mono text-xs" aria-invalid={!!errors.returns?.[i]?.name} {...register(`returns.${i}.name`)} />
              </FormField>
              <FormField id={`sk-ret-type-${i}`} label="Type" className="sm:w-36">
                <Controller
                  control={control}
                  name={`returns.${i}.type`}
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger id={`sk-ret-type-${i}`} className="bg-card">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TYPES.map((t) => (
                          <SelectItem key={t.value} value={t.value}>
                            {t.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </FormField>
              <FormField id={`sk-ret-desc-${i}`} label="Description" className="flex-1" error={errors.returns?.[i]?.description?.message}>
                <Input id={`sk-ret-desc-${i}`} className="bg-card" {...register(`returns.${i}.description`)} />
              </FormField>
              <FormField id={`sk-ret-req-${i}`} label="Required" className="sm:w-20">
                <Controller control={control} name={`returns.${i}.required`} render={({ field }) => <Switch id={`sk-ret-req-${i}`} checked={field.value} onCheckedChange={field.onChange} />} />
              </FormField>
              <Button type="button" variant="ghost" size="icon" className="sm:mt-6" aria-label={`Remove result ${i + 1}`} onClick={() => returns.remove(i)}>
                <X className="size-4" />
              </Button>
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" className="self-start" disabled={returns.fields.length >= 12} onClick={() => returns.append({ name: '', type: 'text', required: true, description: '' })} data-testid="add-skill-result">
            <Plus className="size-4" /> Add a result
          </Button>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Success checks</span>
          {success.fields.map((f, i) => (
            <div key={f.id} className="flex items-start gap-2">
              <FormField id={`sk-success-${i}`} label={`Check ${i + 1}`} className="flex-1" error={errors.success?.[i]?.line?.message}>
                <Input id={`sk-success-${i}`} className="bg-card" aria-invalid={!!errors.success?.[i]?.line} {...register(`success.${i}.line`)} />
              </FormField>
              <Button type="button" variant="ghost" size="icon" className="mt-6" aria-label={`Remove check ${i + 1}`} onClick={() => success.remove(i)}>
                <X className="size-4" />
              </Button>
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" className="self-start" disabled={success.fields.length >= 8} onClick={() => success.append({ line: '' })} data-testid="add-skill-success">
            <Plus className="size-4" /> Add a check
          </Button>
        </div>
      </fieldset>
    </SettingsSection>
  );
}
