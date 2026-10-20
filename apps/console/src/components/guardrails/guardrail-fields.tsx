'use client';

import { FormField } from '@/components/shared/form-field';
import { TagInput } from '@/components/shared/tag-input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

export interface GuardrailDraft {
  topics: string[];
  scopes: Record<string, string>;
  message: string;
  /** Show the answer only once it has passed the check; off, it streams and is replaced if the check then fails. */
  holdUntilChecked: boolean;
}

export type GuardrailErrors = { topics?: string; message?: string; submit?: string };

/** What must be filled before a guardrail version saves; the service refuses the same. */
export const guardrailErrors = (d: GuardrailDraft): GuardrailErrors => ({
  topics: d.topics.length ? undefined : 'Add at least one topic it blocks.',
  message: d.message.trim() ? undefined : 'Write what the person reads instead of an answer.',
});

/** Only the topics still listed keep a scope; the service drops the rest too. */
export const keptScopes = (d: GuardrailDraft) => Object.fromEntries(d.topics.map((t) => [t, (d.scopes[t] ?? '').trim()]).filter(([, s]) => s));

/** A guardrail version's topics, what each covers, and the message shown instead of an answer: create and edit share it. */
export function GuardrailFields({ value, onChange, errors }: { value: GuardrailDraft; onChange: (d: GuardrailDraft) => void; errors: GuardrailErrors }) {
  return (
    <div className="flex flex-col gap-4">
      <FormField id="guardrail-topics" label="Blocked topics" error={errors.topics} hint="Press Enter after each topic.">
        <TagInput id="guardrail-topics" value={value.topics} onChange={(topics) => onChange({ ...value, topics })} placeholder="e.g. investment advice" />
      </FormField>
      {value.topics.map((t, i) => (
        <FormField key={t} id={`guardrail-scope-${i}`} label={`What “${t}” covers`} optional hint="Say what it covers and what it does not. The check reads this beside the topic, so a nearby question is not refused.">
          <Textarea id={`guardrail-scope-${i}`} rows={2} value={value.scopes[t] ?? ''} onChange={(e) => onChange({ ...value, scopes: { ...value.scopes, [t]: e.target.value } })} placeholder="e.g. Whether to buy, sell or hold a security. Not: comparing the bank's own savings products." data-testid="guardrail-scope" />
        </FormField>
      ))}
      <FormField id="guardrail-message" label="Message instead of an answer" error={errors.message ?? errors.submit}>
        <Textarea id="guardrail-message" rows={3} value={value.message} aria-invalid={!!(errors.message ?? errors.submit)} onChange={(e) => onChange({ ...value, message: e.target.value })} placeholder="e.g. I can't give investment advice. A licensed adviser can help with that." />
      </FormField>
      <div className="flex items-start gap-3">
        <Switch id="guardrail-hold" checked={value.holdUntilChecked} onCheckedChange={(holdUntilChecked) => onChange({ ...value, holdUntilChecked })} className="mt-0.5" data-testid="guardrail-hold" />
        <Label htmlFor="guardrail-hold" className="flex flex-col items-start gap-0.5 font-normal">
          <span className="font-medium">Hold the answer until it is checked</span>
          <span className="text-xs text-muted-foreground">Off, the answer appears as it is written and is replaced if the check then finds the topic. On, nothing shows until the check passes, so replies take longer.</span>
        </Label>
      </div>
    </div>
  );
}
