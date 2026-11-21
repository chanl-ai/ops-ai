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
import { Switch } from '@/components/ui/switch';
import type { SkillInputField } from '@/lib/types/skills';

const INPUT_NAME = /^[a-z][a-z0-9_]{0,63}$/;
const MAX_INPUTS = 20;

/** The limits are the service's (a skill's inputs): 20 inputs, a description of 500 characters. */
export const skillInputsSchema = z.object({
  inputs: z
    .array(
      z.object({
        name: z.string().regex(INPUT_NAME, 'Lower-case letters, digits and underscores, starting with a letter, e.g. charge_id.'),
        description: z.string().max(500, 'Keep it under 500 characters.'),
        required: z.boolean(),
      }),
    )
    .max(MAX_INPUTS, `A skill takes at most ${MAX_INPUTS} inputs.`)
    .refine((rows) => new Set(rows.map((r) => r.name)).size === rows.length, 'Each input needs its own name.'),
});
export type SkillInputsForm = z.infer<typeof skillInputsSchema>;

const fromForm = (f: SkillInputsForm): SkillInputField[] => f.inputs.map((i) => ({ name: i.name, type: 'string', description: i.description.trim(), required: i.required }));

/**
 * What a skill asks for when it starts. The list is stored with the draft; an agent's reply does not read it yet, so
 * a required input does not hold a skill back. The values are passed up on every valid change and saved with the rest
 * of the draft; `onValidity` tells the page to hold the save while a field is wrong.
 */
export function SkillInputsSection({ value, onChange, onValidity, disabled }: { value: SkillInputField[]; onChange: (next: SkillInputField[]) => void; onValidity: (valid: boolean) => void; disabled?: boolean }) {
  const form = useForm<SkillInputsForm>({ resolver: zodResolver(skillInputsSchema), defaultValues: { inputs: value.map(({ name, description, required }) => ({ name, description, required })) }, mode: 'onChange' });
  const { control, register, formState, watch } = form;
  const inputs = useFieldArray({ control, name: 'inputs' });
  const errors = formState.errors.inputs;

  React.useEffect(() => {
    const sub = watch((values) => {
      const parsed = skillInputsSchema.safeParse(values);
      onValidity(parsed.success);
      if (parsed.success) onChange(fromForm(parsed.data));
    });
    return () => sub.unsubscribe();
  }, [watch, onChange, onValidity]);

  return (
    <SettingsSection title="Inputs" description="The values this skill takes when it starts. They are saved with the draft. A skill with steps does not start until every required input is given: the agent asks the person for a missing one. A step's rule can read an input as inputs.name.">
      <fieldset disabled={disabled} className="flex flex-col gap-2" data-testid="skill-inputs-section">
        {inputs.fields.length === 0 && <p className="text-sm text-muted-foreground">No inputs. The skill uses what the agent already knows. Add an input only when the caller must pass something in.</p>}
        {inputs.fields.map((f, i) => (
          <div key={f.id} className="flex flex-col gap-2 sm:flex-row sm:items-start">
            <FormField id={`sk-input-name-${i}`} label="Name" className="sm:w-48" error={errors?.[i]?.name?.message}>
              <Input id={`sk-input-name-${i}`} className="bg-card font-mono text-xs" aria-invalid={!!errors?.[i]?.name} {...register(`inputs.${i}.name`)} />
            </FormField>
            <FormField id={`sk-input-desc-${i}`} label="Description" className="flex-1" error={errors?.[i]?.description?.message}>
              <Input id={`sk-input-desc-${i}`} className="bg-card" aria-invalid={!!errors?.[i]?.description} {...register(`inputs.${i}.description`)} />
            </FormField>
            <FormField id={`sk-input-req-${i}`} label="Required" className="sm:w-20">
              <Controller control={control} name={`inputs.${i}.required`} render={({ field }) => <Switch id={`sk-input-req-${i}`} checked={field.value} onCheckedChange={field.onChange} disabled={disabled} />} />
            </FormField>
            <Button type="button" variant="ghost" size="icon" className="sm:mt-6" aria-label={`Remove input ${i + 1}`} onClick={() => inputs.remove(i)}>
              <X className="size-4" />
            </Button>
          </div>
        ))}
        {errors?.root?.message && <p className="text-sm text-destructive-text">{errors.root.message}</p>}
        <Button type="button" variant="outline" size="sm" className="self-start" disabled={inputs.fields.length >= MAX_INPUTS} onClick={() => inputs.append({ name: '', description: '', required: true })} data-testid="add-skill-input">
          <Plus className="size-4" /> Add
        </Button>
      </fieldset>
    </SettingsSection>
  );
}
