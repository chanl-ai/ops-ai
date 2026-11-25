'use client';

import * as React from 'react';
import { Plus, X } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';

type Params = Record<string, unknown>;

/** The part of JSON Schema the form reads; `x-` keys are this form's own hints. */
export interface Schema {
  type?: string;
  enum?: unknown[];
  oneOf?: { const?: unknown; title?: string }[];
  anyOf?: Schema[];
  default?: unknown;
  properties?: Record<string, Schema>;
  items?: Schema;
  required?: string[];
  title?: string;
  description?: string;
  format?: string;
  /** Names a widget by hand where the type alone does not decide it. */
  'x-widget'?: string;
  /** Reserved for secret values: a field marked so is drawn by the `secret` renderer when a page supplies one. */
  'x-secret'?: boolean;
}

/** One field of a form: its label, the widget that edits it, and for a `list` the form of each item. */
export interface FieldSpec {
  label: string;
  widget: string;
  help?: string;
  placeholder?: string;
  item?: FormSpec;
}

/** A form: one field per property, in order. */
export interface FormSpec {
  order: string[];
  fields: Record<string, FieldSpec>;
}

const upper = (v: string) => v.charAt(0).toUpperCase() + v.slice(1);
const words = (name: string) => upper(name.replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase());

/**
 * A field's choices with the words to show for each: JSON Schema's `oneOf` of `{ const, title }` names each option,
 * and a plain `enum` value shows as written with a capital first letter. A setting that also takes a path (`anyOf`
 * of the choices and `$.…`) lists the choices.
 */
export function schemaChoices(schema: { enum?: unknown[]; oneOf?: { const?: unknown; title?: string }[]; anyOf?: { enum?: unknown[] }[] }): { value: string; label: string }[] {
  const titled = (schema.oneOf ?? []).filter((o) => o.const !== undefined);
  if (titled.length) return titled.map((o) => ({ value: String(o.const), label: o.title ?? upper(String(o.const)) }));
  return (schema.enum ?? schema.anyOf?.find((s) => s.enum)?.enum ?? []).map((v) => ({ value: String(v), label: upper(String(v)) }));
}

/** The form a JSON Schema's properties describe: a label from `title`, help from `description`, a widget from the type. */
export function formFromSchema(schema: Schema): FormSpec {
  const fields: Record<string, FieldSpec> = {};
  for (const [name, prop] of Object.entries(schema.properties ?? {})) {
    const widget =
      prop['x-widget'] ??
      (prop.enum || prop.oneOf ? 'select' : prop.type === 'boolean' ? 'switch' : prop.type === 'integer' || prop.type === 'number' ? 'number' : prop.type === 'array' ? 'list' : prop.format === 'textarea' ? 'textarea' : 'text');
    fields[name] = { label: prop.title ?? words(name), widget, help: prop.description, item: widget === 'list' && prop.items?.properties ? formFromSchema(prop.items) : undefined };
  }
  return { order: Object.keys(fields), fields };
}

export const asObject = (v: unknown): Params => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Params) : {});
export const asList = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
/** Drops a cleared setting rather than storing an empty value the schema may refuse. */
export const without = (p: Params, key: string, value: unknown): Params => {
  const next = { ...p };
  if (value === undefined || value === '') delete next[key];
  else next[key] = value;
  return next;
};

export const NONE = '__none__';

/** What a renderer is given for one field. */
export interface FieldContext {
  id: string;
  spec: FieldSpec;
  schema: Schema;
  value: unknown;
  onChange: (v: unknown) => void;
  testId?: string;
  readOnly?: boolean;
}
/** Draws a widget the form does not know itself; returns nothing to leave the field to the form. */
export type FieldRenderer = (ctx: FieldContext) => React.ReactNode | undefined;

/**
 * One form from a JSON Schema: a control per property, reading and writing the same object a JSON edit would, so the
 * server's check of the saved value is the only validation. Widgets the form does not draw (a step picker, a mapping)
 * come from `renderers`, keyed by widget name; a page that stores secrets supplies a `secret` renderer, and a field
 * whose schema sets `x-secret` is drawn by it, so a secret never falls back to a plain text box.
 */
export function SchemaForm({
  schema,
  form,
  value,
  idPrefix,
  onChange,
  errors,
  testIds,
  renderers,
  readOnly,
  testId = 'schema-form',
}: {
  schema: Schema;
  /** The form to draw; by default the one the schema describes. */
  form?: FormSpec;
  value: Params;
  idPrefix: string;
  onChange: (next: Params) => void;
  /** The server's check messages by property name, each shown under its field. */
  errors?: Record<string, string>;
  /** A control's test id, by property name. */
  testIds?: Record<string, string>;
  renderers?: Record<string, FieldRenderer>;
  /** Draws every control disabled and no add or remove buttons. */
  readOnly?: boolean;
  testId?: string;
}) {
  const spec = form ?? formFromSchema(schema);
  const required = new Set(schema.required ?? []);
  return (
    <div className="flex flex-col gap-4" data-testid={testId}>
      {spec.order.map((name) => {
        const field = spec.fields[name];
        const prop = schema.properties?.[name] ?? {};
        const id = `${idPrefix}-${name}`;
        const ctx: FieldContext = { id, spec: field, schema: prop, value: value[name], onChange: (v) => onChange(without(value, name, v)), testId: testIds?.[name], readOnly };
        const custom = (prop['x-secret'] ? renderers?.secret : undefined) ?? renderers?.[field.widget];
        return (
          <FormField key={name} id={id} label={field.label} optional={!required.has(name)} hint={field.help} error={errors?.[name]}>
            {custom?.(ctx) ?? <BasicControl {...ctx} renderers={renderers} />}
          </FormField>
        );
      })}
    </div>
  );
}

function BasicControl({ id, spec, schema, value, onChange, testId, readOnly, renderers }: FieldContext & { renderers?: Record<string, FieldRenderer> }) {
  switch (spec.widget) {
    case 'text':
      return <Input id={id} value={typeof value === 'string' ? value : ''} disabled={readOnly} placeholder={spec.placeholder ?? (typeof schema.default === 'string' ? `e.g. ${schema.default}` : undefined)} onChange={(e) => onChange(e.target.value || undefined)} data-field={id} />;
    case 'textarea':
      return <Textarea id={id} value={typeof value === 'string' ? value : ''} disabled={readOnly} rows={4} onChange={(e) => onChange(e.target.value || undefined)} data-field={id} />;
    case 'number':
      return <Input id={id} type="number" inputMode="decimal" disabled={readOnly} value={typeof value === 'number' ? String(value) : ''} onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} data-field={id} />;
    case 'date':
      return <Input id={id} type="date" disabled={readOnly} value={typeof value === 'string' ? value : ''} onChange={(e) => onChange(e.target.value || undefined)} data-field={id} />;
    case 'switch':
      return <Switch id={id} checked={value === true} disabled={readOnly} onCheckedChange={(c) => onChange(c)} />;
    case 'select':
      return <EnumSelect id={id} schema={schema} value={value} onChange={onChange} testId={testId} disabled={readOnly} />;
    case 'list':
      return spec.item ? <ListInput id={id} item={spec.item} schema={schema.items ?? {}} value={asList(value)} onChange={(v) => onChange(v.length ? v : undefined)} renderers={renderers} readOnly={readOnly} /> : null;
    default:
      return null;
  }
}

function EnumSelect({ id, schema, value, onChange, testId, disabled }: { id: string; schema: Schema; value: unknown; onChange: (v: unknown) => void; testId?: string; disabled?: boolean }) {
  // A saved value the choices do not list (a path) stays shown as itself.
  const listed = schemaChoices(schema);
  const options = typeof value === 'string' && value && !listed.some((o) => o.value === value) ? [...listed, { value, label: value }] : listed;
  const fallback = schema.default !== undefined ? `Default (${String(schema.default)})` : 'Not set';
  return (
    <Select value={typeof value === 'string' ? value : NONE} onValueChange={(v) => onChange(v === NONE ? undefined : v)} disabled={disabled}>
      <SelectTrigger id={id} className="w-full" data-field={id} data-testid={testId}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>{fallback}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** A list of objects, each edited with the item form its field declares. */
function ListInput({ id, item, schema, value, onChange, renderers, readOnly }: { id: string; item: FormSpec; schema: Schema; value: unknown[]; onChange: (v: unknown[]) => void; renderers?: Record<string, FieldRenderer>; readOnly?: boolean }) {
  return (
    <div className="flex flex-col gap-2" data-testid={`${id}-rows`}>
      {value.map((entry, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-md border p-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">{i + 1}</span>
            {!readOnly && (
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${i + 1}`} onClick={() => onChange(value.filter((_, j) => j !== i))}>
                <X />
              </Button>
            )}
          </div>
          <SchemaForm schema={schema} form={item} value={asObject(entry)} idPrefix={`${id}-${i}`} renderers={renderers} readOnly={readOnly} onChange={(next) => onChange(value.map((e, j) => (j === i ? next : e)))} />
        </div>
      ))}
      {!readOnly && (
        <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => onChange([...value, {}])}>
          <Plus /> Add
        </Button>
      )}
    </div>
  );
}
