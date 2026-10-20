'use client';

import * as React from 'react';

import { FormField } from '@/components/shared/form-field';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import type { SchemaField } from '@/lib/types/tool-modules';

/** A list or object field's sample as JSON text: kept as typed until it parses, so a half-typed value is not lost. */
function JsonValue({ id, label, value, onChange }: { id: string; label: string; value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = React.useState(() => JSON.stringify(value ?? null, null, 2));
  const [error, setError] = React.useState<string>();
  return (
    <FormField id={id} label={label} error={error} hint="JSON">
      <Textarea
        id={id}
        rows={4}
        className="font-mono text-xs"
        value={text}
        spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          try {
            onChange(JSON.parse(e.target.value));
            setError(undefined);
          } catch (err) {
            setError((err as Error).message);
          }
        }}
      />
    </FormField>
  );
}

/** One input per data field, of the field's type, for the data the preview fills the widget with. */
export function SampleEditor({ fields, value, onChange }: { fields: SchemaField[]; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void }) {
  const put = (name: string, v: unknown) => onChange(Object.fromEntries(Object.entries({ ...value, [name]: v }).filter(([, x]) => x !== undefined)));
  if (!fields.length) return <p className="text-sm text-muted-foreground">Add a field above to give it a sample value.</p>;
  return (
    <div className="grid gap-4 sm:grid-cols-2" data-testid="sample-editor">
      {fields
        .filter((f) => f.name)
        .map((f) => {
          const id = `sample-${f.name}`;
          const v = value[f.name];
          if (f.type === 'array' || f.type === 'object') return <JsonValue key={f.name} id={id} label={f.name} value={v} onChange={(x) => put(f.name, x)} />;
          if (f.type === 'boolean')
            return (
              <FormField key={f.name} id={id} label={f.name}>
                <Switch id={id} checked={v === true} onCheckedChange={(x) => put(f.name, x)} />
              </FormField>
            );
          if (f.enum?.length)
            return (
              <FormField key={f.name} id={id} label={f.name}>
                <Select value={typeof v === 'string' ? v : ''} onValueChange={(x) => put(f.name, x)}>
                  <SelectTrigger id={id} className="w-full">
                    <SelectValue placeholder="Choose a value" />
                  </SelectTrigger>
                  <SelectContent>
                    {f.enum.map((o) => (
                      <SelectItem key={o} value={o}>
                        {o}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
            );
          const numeric = f.type === 'number' || f.type === 'integer';
          return (
            <FormField key={f.name} id={id} label={f.name} optional={!f.required}>
              <Input id={id} type={numeric ? 'number' : 'text'} value={v === undefined || v === null ? '' : String(v)} onChange={(e) => put(f.name, e.target.value === '' ? undefined : numeric ? Number(e.target.value) : e.target.value)} />
            </FormField>
          );
        })}
    </div>
  );
}
