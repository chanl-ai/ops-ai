'use client';

import { ChevronDown } from 'lucide-react';

import { HealthLine } from '@/components/connections/health-line';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { isRequired, type EnvDraft, type Environment, type FieldGroups, type KindField } from '@/lib/connect-plan';

/** One environment's section of the connect dialog: its fields, More settings, its test button and last result. */
export function EnvSection({
  env,
  label,
  draft,
  groups,
  busy,
  canTest,
  onSetting,
  onSecret,
  onTest,
  testLabel = 'Run test',
}: {
  env: Environment;
  label: string;
  draft: EnvDraft;
  groups: FieldGroups;
  busy: boolean;
  canTest: boolean;
  onSetting: (name: string, value: string) => void;
  onSecret: (name: string, value: string) => void;
  onTest: () => void;
  testLabel?: string;
}) {
  const input = (f: KindField) => {
    const id = `${env}-${f.name}`;
    if (f.secret) {
      return (
        <Input
          id={id}
          type="password"
          autoComplete="off"
          value={draft.secrets[f.name] ?? ''}
          onChange={(e) => onSecret(f.name, e.target.value)}
          placeholder={draft.secretSet[f.name] ? 'Sealed · type to replace' : undefined}
        />
      );
    }
    if (f.choices?.length) {
      return (
        <Select value={draft.settings[f.name] ?? ''} onValueChange={(v) => onSetting(f.name, v)}>
          <SelectTrigger id={id} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {f.choices.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }
    return <Input id={id} value={draft.settings[f.name] ?? ''} onChange={(e) => onSetting(f.name, e.target.value)} />;
  };
  const field = (f: KindField) => (
    <FormField key={f.name} id={`${env}-${f.name}`} label={f.label} optional={!isRequired(f, draft.settings)} hint={f.help ?? undefined}>
      {input(f)}
    </FormField>
  );
  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-lg border p-4" data-testid={`env-${env}`} aria-label={label}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}</h3>
        <LoadingButton
          type="button"
          size="sm"
          variant="outline"
          onClick={onTest}
          isLoading={draft.status === 'testing'}
          disabled={!canTest || busy}
          data-testid={`test-${env}`}
        >
          {testLabel}
        </LoadingButton>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">{groups.main.map(field)}</div>
      {groups.more.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button type="button" variant="ghost" size="sm" className="-ml-2 text-muted-foreground">
              <ChevronDown />
              More settings
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="grid gap-3 pt-2 sm:grid-cols-2">{groups.more.map(field)}</CollapsibleContent>
        </Collapsible>
      )}
      {draft.health && <HealthLine health={draft.health} testId={`health-${env}`} who={false} />}
    </section>
  );
}
