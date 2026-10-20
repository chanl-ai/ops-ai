'use client';

import type * as React from 'react';
import { Lock, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { SchemaField, SchemaType } from '@/lib/types/tool-modules';

const TYPES: SchemaType[] = ['string', 'integer', 'number', 'boolean', 'object', 'array'];

/** One field as typed: allowed values and the default stay text until saved, so half-typed values are not lost. */
export type FieldDraft = { name: string; type: SchemaType; required: boolean; description: string; allowed: string; dflt: string; format?: string; example?: string };

export const fieldDrafts = (fields: SchemaField[]): FieldDraft[] =>
  fields.map((f) => ({ name: f.name, type: f.type, required: f.required, description: f.description ?? '', allowed: (f.enum ?? []).join(', '), dflt: f.default === undefined ? '' : String(f.default), format: f.format, example: f.example }));

/** The default as the field's type. A value that does not parse is sent as typed, so the service names the field. */
function parsedDefault(type: SchemaType, text: string): string | number | boolean | undefined {
  const t = text.trim();
  if (!t) return undefined;
  if (type === 'integer' && /^-?\d+$/.test(t)) return Number(t);
  if (type === 'number' && t !== '' && !Number.isNaN(Number(t))) return Number(t);
  if (type === 'boolean' && (t === 'true' || t === 'false')) return t === 'true';
  return t;
}

export function schemaOf(drafts: FieldDraft[]): SchemaField[] {
  return drafts.map((d) => {
    const enumValues = d.allowed
      .split(',')
      .map((v) => v.trim())
      .filter(Boolean);
    const dflt = d.required ? undefined : parsedDefault(d.type, d.dflt);
    return {
      name: d.name.trim(),
      type: d.type,
      required: d.required,
      ...(d.description.trim() ? { description: d.description.trim() } : {}),
      ...(d.format ? { format: d.format } : {}),
      ...(enumValues.length ? { enum: enumValues } : {}),
      ...(d.example ? { example: d.example } : {}),
      ...(dflt !== undefined ? { default: dflt } : {}),
    };
  });
}

/**
 * What an agent may send, edited in place. Each row is one field; a field the record binding fills cannot be renamed
 * or removed here. `errors` maps a field name to the service's refusal so it shows on that row. `note` replaces the
 * line under the table, which by default says how a tool operation's change is versioned.
 */
export function InputSchemaEditor({ value, onChange, boundArg, errors, note }: { value: FieldDraft[]; onChange: (v: FieldDraft[]) => void; boundArg?: string; errors?: Record<string, string>; note?: React.ReactNode }) {
  const set = (i: number, p: Partial<FieldDraft>) => onChange(value.map((f, n) => (n === i ? { ...f, ...p } : f)));
  return (
    <div className="flex flex-col gap-2" data-testid="input-schema-editor">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Field</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Required</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Allowed values</TableHead>
            <TableHead>Default</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {value.map((f, i) => {
            const bound = !!boundArg && f.name === boundArg;
            const error = errors?.[f.name.trim()];
            return (
              <TableRow key={i} data-testid={`input-field-${i}`}>
                <TableCell className="min-w-36 align-top">
                  <Input aria-label={`Field ${i + 1} name`} value={f.name} onChange={(e) => set(i, { name: e.target.value })} disabled={bound} className="font-mono text-xs" aria-invalid={!!error} />
                  {bound && (
                    <span className="mt-1 inline-flex items-center gap-0.5 text-[11px] text-muted-foreground">
                      <Lock className="size-3" /> Bound
                    </span>
                  )}
                  {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                </TableCell>
                <TableCell className="min-w-28 align-top">
                  <Select value={f.type} onValueChange={(v) => set(i, { type: v as SchemaType, ...(v === 'string' ? {} : { allowed: '' }) })}>
                    <SelectTrigger aria-label={`Field ${i + 1} type`} className="w-full text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TYPES.map((t) => (
                        <SelectItem key={t} value={t}>
                          {t}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell className="align-top">
                  <Checkbox aria-label={`Field ${i + 1} required`} checked={f.required} onCheckedChange={(v) => set(i, { required: v === true, ...(v === true ? { dflt: '' } : {}) })} className="mt-2" />
                </TableCell>
                <TableCell className="min-w-40 align-top">
                  <Input aria-label={`Field ${i + 1} description`} value={f.description} onChange={(e) => set(i, { description: e.target.value })} className="text-xs" />
                </TableCell>
                <TableCell className="min-w-32 align-top">
                  <Input aria-label={`Field ${i + 1} allowed values`} value={f.allowed} onChange={(e) => set(i, { allowed: e.target.value })} disabled={f.type !== 'string'} placeholder={f.type === 'string' ? 'a, b, c' : 'Strings only'} className="text-xs" />
                </TableCell>
                <TableCell className="min-w-28 align-top">
                  <Input aria-label={`Field ${i + 1} default`} value={f.dflt} onChange={(e) => set(i, { dflt: e.target.value })} disabled={f.required} placeholder={f.required ? 'Required' : 'None'} className="text-xs" />
                </TableCell>
                <TableCell className="align-top">
                  <Button variant="ghost" size="icon" aria-label={`Remove ${f.name || `field ${i + 1}`}`} disabled={bound} onClick={() => onChange(value.filter((_, n) => n !== i))}>
                    <Trash2 className="size-4" />
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <div>
        <Button variant="outline" size="sm" onClick={() => onChange([...value, { name: '', type: 'string', required: false, description: '', allowed: '', dflt: '' }])} data-testid="input-add-field">
          <Plus className="size-4" /> Add field
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">{note ?? 'A new required field, a removed field, a type change or new allowed values is a major version that Security reviews. Descriptions and defaults are minor.'}</p>
    </div>
  );
}
