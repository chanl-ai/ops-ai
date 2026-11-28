'use client';

import * as React from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { z } from 'zod';

import { FormField } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { Textarea } from '@/components/ui/textarea';

/** `useWhenMax` is the service's limit; an always-on skill is added to every turn, so it needs no use-when line. */
export const skillWhenSchema = (useWhenMax: number, needsUseWhen: boolean) =>
  z.object({
    useWhen: z
      .string()
      .max(useWhenMax, `Keep it under ${useWhenMax.toLocaleString('en-CA')} characters.`)
      .refine((v) => !needsUseWhen || v.trim().length > 0, 'Say when the skill should be used.'),
    notWhen: z.string().max(1024, 'Keep it under 1,024 characters.'),
  });
export type SkillWhen = z.infer<ReturnType<typeof skillWhenSchema>>;

export interface SkillWhenHandle {
  /** Shows what is wrong and moves to the first field that is; true when nothing is. */
  check(): Promise<boolean>;
}

/**
 * When the agent picks the skill and when it leaves it alone, above the steps. Every edit is passed up and saved with
 * the rest of the draft; `onValidity` tells the page whether a save can go, and `controls.check` moves to the field
 * that stops it.
 */
export function SkillWhenSection({
  value,
  onChange,
  onValidity,
  useWhenMax,
  needsUseWhen,
  showNotWhen,
  notWhenProblem,
  disabled,
  controls,
}: {
  value: SkillWhen;
  onChange: (next: SkillWhen) => void;
  onValidity: (valid: boolean) => void;
  useWhenMax: number;
  /** False for an always-on skill, which hides the field. */
  needsUseWhen: boolean;
  /** Only a skill with steps has a not-when line. */
  showNotWhen: boolean;
  /** A publish problem the service placed on the not-when line. */
  notWhenProblem?: string;
  disabled?: boolean;
  controls?: React.Ref<SkillWhenHandle>;
}) {
  const schema = React.useMemo(() => skillWhenSchema(useWhenMax, needsUseWhen), [useWhenMax, needsUseWhen]);
  const { register, formState, watch, getValues, trigger } = useForm<SkillWhen>({ resolver: zodResolver(schema), defaultValues: value, mode: 'onBlur' });
  const errors = formState.errors;

  React.useEffect(() => {
    const sub = watch((values) => {
      onChange({ useWhen: values.useWhen ?? '', notWhen: values.notWhen ?? '' });
      onValidity(schema.safeParse(values).success);
    });
    return () => sub.unsubscribe();
  }, [watch, onChange, onValidity, schema]);
  // Changing Loading changes whether the use-when line is needed, without a keystroke here.
  React.useEffect(() => {
    onValidity(schema.safeParse(getValues()).success);
  }, [schema, getValues, onValidity]);

  React.useImperativeHandle(controls, () => ({ check: () => trigger(undefined, { shouldFocus: true }) }), [trigger]);

  if (!needsUseWhen && !(showNotWhen && (!disabled || !!value.notWhen.trim()))) return null;
  const used = watch('useWhen')?.length ?? 0;
  return (
    <SettingsSection title="Use when">
      <fieldset disabled={disabled} className="flex flex-col gap-4" data-testid="skill-when-section">
        {needsUseWhen && (
          <FormField id="sk-usewhen" label="Use this skill when" error={errors.useWhen?.message} hint={`The kind of request it handles. ${used.toLocaleString('en-CA')} of ${useWhenMax.toLocaleString('en-CA')} characters.`}>
            <Textarea id="sk-usewhen" rows={2} className="min-h-16 bg-card" placeholder="The request this skill handles. e.g. a customer says their power is out or asks when it will be back." aria-invalid={!!errors.useWhen} data-testid="skill-use-when" {...register('useWhen')} />
          </FormField>
        )}
        {/* A read-only skill with no not-when line has nothing to show there. */}
        {showNotWhen && (!disabled || !!value.notWhen.trim()) && (
          <FormField id="sk-notwhen" label="Not when" optional hint="When the agent should leave this skill alone." error={errors.notWhen?.message ?? notWhenProblem}>
            <Textarea id="sk-notwhen" rows={2} className="bg-card" placeholder="When to leave this skill alone. e.g. the customer is reporting a gas smell." aria-invalid={!!errors.notWhen || !!notWhenProblem} data-testid="skill-not-when" {...register('notWhen')} />
          </FormField>
        )}
      </fieldset>
    </SettingsSection>
  );
}
