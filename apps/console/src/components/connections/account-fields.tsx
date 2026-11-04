'use client';

import * as React from 'react';
import { ChevronDown, FileUp } from 'lucide-react';

import { HealthLine } from '@/components/connections/health-line';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { isRequired, type Draft, type FieldGroups, type KindField } from '@/lib/connect-plan';

/** An account's keys in the connect dialog: its fields, More settings, its test button and last result. */
export function AccountFields({
  label = 'Keys',
  draft,
  groups,
  busy,
  canTest,
  onSetting,
  onSecret,
  onTest,
  testLabel = 'Run test',
}: {
  label?: string;
  draft: Draft;
  groups: FieldGroups;
  busy: boolean;
  canTest: boolean;
  onSetting: (name: string, value: string) => void;
  onSecret: (name: string, value: string) => void;
  onTest: () => void;
  testLabel?: string;
}) {
  const input = (f: KindField) => {
    const id = `account-${f.name}`;
    if (f.pem) {
      const set = f.secret ? onSecret : onSetting;
      const value = (f.secret ? draft.secrets[f.name] : draft.settings[f.name]) ?? '';
      return (
        <PemInput
          id={id}
          value={value}
          onChange={(v) => set(f.name, v)}
          placeholder={f.secret && draft.secretSet[f.name] ? 'Sealed · paste or read a file to replace' : '-----BEGIN …'}
        />
      );
    }
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
    <FormField key={f.name} id={`account-${f.name}`} label={f.label} optional={!isRequired(f, draft.settings)} hint={f.help ?? undefined} className={f.pem ? 'sm:col-span-2' : undefined}>
      {input(f)}
    </FormField>
  );
  return (
    <section className="flex min-w-0 flex-col gap-3 rounded-lg border p-4" data-testid="account-fields" aria-label={label}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{label}</h3>
        <LoadingButton
          type="button"
          size="sm"
          variant="outline"
          onClick={onTest}
          isLoading={draft.status === 'testing'}
          disabled={!canTest || busy}
          data-testid="account-test"
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
      {draft.health && <HealthLine health={draft.health} testId="account-health" who={false} />}
    </section>
  );
}

/**
 * PEM text as a certificate or key file holds it: a multi-line box, or read from the file on this device. The file is
 * read in the browser and never uploaded anywhere but the connection's sealed field.
 */
function PemInput({ id, value, onChange, placeholder }: { id: string; value: string; onChange: (v: string) => void; placeholder: string }) {
  const picker = React.useRef<HTMLInputElement>(null);
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Textarea
        id={id}
        rows={4}
        spellCheck={false}
        autoComplete="off"
        className="font-mono text-xs"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      <input
        ref={picker}
        type="file"
        accept=".pem,.crt,.cer,.key,.txt"
        className="hidden"
        data-testid={`${id}-file`}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void file.text().then(onChange);
          e.target.value = '';
        }}
      />
      <Button type="button" variant="ghost" size="sm" className="-ml-2 self-start text-muted-foreground" onClick={() => picker.current?.click()}>
        <FileUp />
        Read from a file
      </Button>
    </div>
  );
}
