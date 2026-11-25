'use client';

import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { signInChoiceWords, signInFor, type SignInSetting } from '@/lib/login-words';
import { cn } from '@/lib/utils';

export type SignIn = SignInSetting;

type Choice = 'shared' | 'each';

/**
 * Whose login an account's calls use: the team's shared login, or each person's own. A private login is a person's
 * own account under My accounts, so it is not a choice here. `signedIn` counts the people who have signed in to the
 * account (for example 3 of 12), shown under "Each person signs in". `offered` lists the values the app allows.
 */
export function WhoSignsIn({
  value,
  onChange,
  offered,
  signedIn,
}: {
  value: SignIn;
  onChange: (v: SignIn) => void;
  offered?: readonly string[];
  signedIn?: { count: number; of: number };
}) {
  const choices: { value: Choice; label: string; hint: string; allowed: boolean }[] = [
    {
      value: 'shared',
      label: signInChoiceWords('team'),
      hint: 'Every call acts as one login the team signs in, and records who asked.',
      allowed: !offered || offered.includes('team'),
    },
    {
      value: 'each',
      label: signInChoiceWords('person'),
      hint: 'Calls act as the person who asked. Anyone who has not signed in is asked to, once.',
      allowed: !offered || offered.includes('person'),
    },
  ];
  const current: Choice = value === 'team' ? 'shared' : 'each';
  return (
    <RadioGroup
      value={current}
      onValueChange={(v) => onChange(signInFor(v === 'shared' ? 'shared' : 'each'))}
      className="grid gap-2 md:grid-cols-2"
      aria-label="Who signs in"
      data-testid="connect-who"
    >
      {choices
        .filter((o) => o.allowed)
        .map((o) => (
          <label
            key={o.value}
            htmlFor={`who-${o.value}`}
            className={cn('flex cursor-pointer items-start gap-3 rounded-md border p-3', current === o.value && 'border-primary bg-primary/5')}
          >
            <RadioGroupItem value={o.value} id={`who-${o.value}`} className="mt-0.5" />
            <span className="min-w-0">
              <span className="block text-sm font-medium">{o.label}</span>
              <span className="block text-xs text-muted-foreground">{o.hint}</span>
              {o.value === 'each' && signedIn && (
                <span className="mt-1 block text-xs text-muted-foreground" data-testid="who-signed-in-count">
                  {signedIn.count} of {signedIn.of} people signed in
                </span>
              )}
            </span>
          </label>
        ))}
    </RadioGroup>
  );
}
