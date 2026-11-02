'use client';

import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { cn } from '@/lib/utils';

export type SignIn = 'team' | 'person' | 'person_or_team';

const WHO: { value: SignIn; label: string; hint: string }[] = [
  {
    value: 'team',
    label: 'Team account',
    hint: 'Every call signs in as one account the team connects.',
  },
  {
    value: 'person',
    label: 'Each person’s own account',
    hint: 'Calls act as the person who asked. Anyone who has not connected is asked.',
  },
  {
    value: 'person_or_team',
    label: 'Each person, team account as backup',
    hint: 'Runs with nobody behind them use the team account.',
  },
];

/**
 * Whose account a connection's calls sign in with, for a sign-in kind each person can use. `offered` narrows the
 * choices to the ones the system allows (a plugin lists its own); the connect dialog's form for a system and for a
 * plugin both ask it here.
 */
export function WhoSignsIn({ value, onChange, offered }: { value: SignIn; onChange: (v: SignIn) => void; offered?: readonly string[] }) {
  const choices = offered ? WHO.filter((o) => offered.includes(o.value)) : WHO;
  return (
    <RadioGroup
      value={value}
      onValueChange={(v) => onChange(v as SignIn)}
      className="grid gap-2 md:grid-cols-3"
      aria-label="Whose account calls use"
      data-testid="connect-who"
    >
      {choices.map((o) => (
        <label
          key={o.value}
          htmlFor={`who-${o.value}`}
          className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', value === o.value && 'border-primary bg-primary/5')}
        >
          <RadioGroupItem value={o.value} id={`who-${o.value}`} className="mt-0.5" />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{o.label}</span>
            <span className="block text-xs text-muted-foreground">{o.hint}</span>
          </span>
        </label>
      ))}
    </RadioGroup>
  );
}
