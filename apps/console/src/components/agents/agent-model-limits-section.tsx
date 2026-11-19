'use client';

import * as React from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { ChevronDown } from 'lucide-react';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';

import { FormField } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import type { AgentPatterns, ModelAlias, Thinking } from '@/lib/types/domain';

import { modelHint, ModelSelect } from './model-select';

export const THINKING: { value: Thinking; label: string; hint: string }[] = [
  { value: 'default', label: 'Model default', hint: 'The model decides how long to think.' },
  { value: 'low', label: 'Low', hint: 'Quick answers; least cost.' },
  { value: 'medium', label: 'Medium', hint: 'A short plan before answering.' },
  { value: 'high', label: 'High', hint: 'The longest plan; slowest and most costly.' },
];

export const agentLimitsSchema = z.object({
  model: z.string().trim().min(1, 'Choose a model.'),
  thinking: z.enum(['default', 'low', 'medium', 'high']),
  parallelReads: z.boolean(),
});
export type AgentLimitsForm = z.infer<typeof agentLimitsSchema>;

/**
 * The agent's model and how it works through a turn, as a form at the foot of the page: closed it is one control that
 * names the model; open it holds the model, how long it thinks, whether it may read several things at once, and
 * "Rules and limits" (guardrails, refusal, caller limits, memory and the skill menu), which the page hands in unchanged.
 * Values go up on every valid change and save with the rest of the draft.
 */
export function AgentModelLimitsSection({
  model,
  patterns,
  models,
  onChange,
  disabled,
  open,
  onOpenChange,
  children,
}: {
  model: string;
  patterns: AgentPatterns;
  models: ModelAlias[];
  onChange: (next: { model: string; patterns: AgentPatterns }) => void;
  disabled?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}) {
  const form = useForm<AgentLimitsForm>({ resolver: zodResolver(agentLimitsSchema), values: { model, thinking: patterns.thinking, parallelReads: patterns.parallelReads }, mode: 'onBlur' });
  const { control, watch, formState } = form;
  React.useEffect(() => {
    const sub = watch((values) => {
      const parsed = agentLimitsSchema.safeParse(values);
      if (parsed.success) onChange({ model: parsed.data.model, patterns: { thinking: parsed.data.thinking, parallelReads: parsed.data.parallelReads } });
    });
    return () => sub.unsubscribe();
  }, [watch, onChange]);
  const thinking = THINKING.find((t) => t.value === patterns.thinking);
  return (
    <SettingsSection title="Model and limits" description="Which model answers, how it works through a turn, and what callers may change.">
      <Collapsible open={open} onOpenChange={onOpenChange} className="flex flex-col gap-4">
        <CollapsibleTrigger asChild>
          <Button type="button" variant="outline" className="w-full justify-between bg-card sm:w-auto sm:self-start" data-testid="agent-model-limits-toggle">
            <span className="truncate">
              {model || 'No model'} · thinking: {thinking?.label.toLowerCase()}
            </span>
            <ChevronDown className="size-4" aria-hidden />
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="flex flex-col gap-6" data-testid="agent-model-limits">
          <fieldset disabled={disabled} className="grid gap-4 md:grid-cols-2">
            <FormField id="ag-model" label="Model" error={formState.errors.model?.message} hint={modelHint(models, model)}>
              <Controller control={control} name="model" render={({ field }) => <ModelSelect id="ag-model" value={field.value} onValueChange={field.onChange} aliases={models} className="bg-card" invalid={!!formState.errors.model} />} />
            </FormField>
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
            <FormField id="ag-parallel" label="Read several things at once" hint="Lookups that only read may run together. Writes always run one at a time." className="md:col-span-2">
              <Controller control={control} name="parallelReads" render={({ field }) => <Switch id="ag-parallel" checked={field.value} onCheckedChange={field.onChange} />} />
            </FormField>
          </fieldset>
          <div className="flex flex-col gap-4" data-testid="agent-rules-and-limits">
            <h3 className="text-sm font-semibold">Rules and limits</h3>
            {children}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </SettingsSection>
  );
}
