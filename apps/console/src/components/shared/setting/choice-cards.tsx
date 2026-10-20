'use client';

import type { ReactNode } from 'react';

import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { cn } from '@/lib/utils';

export interface Choice {
  value: string;
  title: string;
  description: ReactNode;
}

const CARD = 'flex cursor-pointer items-start gap-3 rounded-lg border bg-card p-4 transition-colors hover:bg-accent/40 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5';

/** Radio or checkbox cards with a title and a description, for policy modes where each option needs explaining. */
export function ChoiceCards({ name, choices, value, onChange, label }: { name: string; choices: Choice[]; value: string; onChange: (v: string) => void; label: string }) {
  return (
    <RadioGroup value={value} onValueChange={onChange} aria-label={label} className="grid gap-3 sm:grid-cols-2">
      {choices.map((c) => (
        <label key={c.value} htmlFor={`${name}-${c.value}`} className={CARD}>
          <RadioGroupItem value={c.value} id={`${name}-${c.value}`} className="mt-0.5" />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{c.title}</span>
            <span className="block text-xs text-muted-foreground">{c.description}</span>
          </span>
        </label>
      ))}
    </RadioGroup>
  );
}

export function ChoiceChecks({ name, choices, value, onChange, label }: { name: string; choices: Choice[]; value: string[]; onChange: (v: string[]) => void; label: string }) {
  return (
    <div role="group" aria-label={label} className="grid gap-3 sm:grid-cols-2">
      {choices.map((c) => (
        <label key={c.value} htmlFor={`${name}-${c.value}`} className={cn(CARD, value.includes(c.value) && 'border-primary bg-primary/5')}>
          <Checkbox id={`${name}-${c.value}`} checked={value.includes(c.value)} onCheckedChange={(on) => onChange(on ? [...value, c.value] : value.filter((x) => x !== c.value))} className="mt-0.5" />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{c.title}</span>
            <span className="block text-xs text-muted-foreground">{c.description}</span>
          </span>
        </label>
      ))}
    </div>
  );
}
