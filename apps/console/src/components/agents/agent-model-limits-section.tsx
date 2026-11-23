'use client';

import * as React from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';

import { FormField } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import type { AgentPatterns, Thinking } from '@/lib/types/domain';

export const THINKING: { value: Thinking; label: string; hint: string }[] = [
  { value: 'default', label: 'Model default', hint: 'The model decides how long to think.' },
  { value: 'low', label: 'Low', hint: 'Quick answers; least cost.' },
  { value: 'medium', label: 'Medium', hint: 'A short plan before answering.' },
  { value: 'high', label: 'High', hint: 'The longest plan; slowest and most costly.' },
];

export const agentLimitsSchema = z.object({
  // Empty until a model is chosen: an agent made from the SDK or the command line has none, and how it thinks still saves.
  model: z.string().trim(),
  thinking: z.enum(['default', 'low', 'medium', 'high']),
  parallelReads: z.boolean(),
});
export type AgentLimitsForm = z.infer<typeof agentLimitsSchema>;

/**
 * How the agent works through a turn, as a form on the Limits page: how long it thinks, whether it may read several things at once, and
 * "Rules and limits" (guardrails, refusal, caller limits, memory and the skill menu), which the page hands in unchanged.
 * Values go up on every valid change and save with the rest of the draft.
 */
export function AgentModelLimitsSection({
  model,
  patterns,
  onChange,
  disabled,
  children,
}: {
  model: string;
  patterns: AgentPatterns;
  onChange: (next: { model: string; patterns: AgentPatterns }) => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  const form = useForm<AgentLimitsForm>({ resolver: zodResolver(agentLimitsSchema), values: { model, thinking: patterns.thinking, parallelReads: patterns.parallelReads }, mode: 'onBlur' });
  const { control, watch } = form;
  React.useEffect(() => {
    const sub = watch((values) => {
      const parsed = agentLimitsSchema.safeParse(values);
      if (parsed.success) onChange({ model: parsed.data.model, patterns: { thinking: parsed.data.thinking, parallelReads: parsed.data.parallelReads } });
    });
    return () => sub.unsubscribe();
  }, [watch, onChange]);
  const thinking = THINKING.find((t) => t.value === patterns.thinking);
  return (
    <SettingsSection title="Limits" description="How the model works through a turn, and what callers may change.">
      <div className="flex flex-col gap-6" data-testid="agent-model-limits">
        <fieldset disabled={disabled} className="grid gap-4 md:grid-cols-2">
          <FormField id="ag-thinking" label="Thinking" hint={thinking?.hint}>
            <Controller
              control={control}
              name="thinking"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="ag-thinking" className="w-full bg-card">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {THINKING.map((t) => (
                      <SelectItem key={t.value} value={t.value}>
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </FormField>
          <FormField id="ag-parallel" label="Read several things at once" hint="Lookups that only read may run together. Writes always run one at a time.">
            <Controller control={control} name="parallelReads" render={({ field }) => <Switch id="ag-parallel" checked={field.value} onCheckedChange={field.onChange} />} />
          </FormField>
        </fieldset>
        <div className="flex flex-col gap-4" data-testid="agent-rules-and-limits">
          <h3 className="text-sm font-semibold">Rules and limits</h3>
          {children}
        </div>
      </div>
    </SettingsSection>
  );
}
