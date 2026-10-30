'use client';

import * as React from 'react';
import { Plus, X } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useEngineOptions } from '@/hooks/engine-queries';
import type { EngineOption, NodeForm, NodeFormField, OptionSource } from '@/lib/types/engine';

type Params = Record<string, unknown>;
type Schema = { type?: string; enum?: unknown[]; oneOf?: { const?: unknown; title?: string }[]; anyOf?: Schema[]; default?: unknown; properties?: Record<string, Schema>; items?: Schema; required?: string[] };

export interface StepRef {
  id: string;
  label: string;
  type: string;
}

/** The node's neighbours: `all` other steps (a review names the tool step it approves, which runs after it), and the
 * `earlier` steps a mapping can read, since only their output exists when this one runs. */
export interface StepRefs {
  all: StepRef[];
  earlier: StepRef[];
}

const NONE = '__none__';

/**
 * A field's choices with the words to show for each: JSON Schema's `oneOf` of `{ const, title }` names each option,
 * and a plain `enum` value shows as written with a capital first letter. A setting that also takes a path (`anyOf`
 * of the choices and `$.…`) lists the choices.
 */
export function schemaChoices(schema: { enum?: unknown[]; oneOf?: { const?: unknown; title?: string }[]; anyOf?: { enum?: unknown[] }[] }): { value: string; label: string }[] {
  const upper = (v: string) => v.charAt(0).toUpperCase() + v.slice(1);
  const titled = (schema.oneOf ?? []).filter((o) => o.const !== undefined);
  if (titled.length) return titled.map((o) => ({ value: String(o.const), label: o.title ?? upper(String(o.const)) }));
  return (schema.enum ?? schema.anyOf?.find((s) => s.enum)?.enum ?? []).map((v) => ({ value: String(v), label: upper(String(v)) }));
}

const asObject = (v: unknown): Params => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Params) : {});
const asList = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
/** Drops a cleared setting rather than storing an empty value the schema may refuse. */
const without = (p: Params, key: string, value: unknown): Params => {
  const next = { ...p };
  if (value === undefined || value === '') delete next[key];
  else next[key] = value;
  return next;
};

/**
 * A node's settings as the form its type declares (`ui`): one control per parameter, in the type's order. The form
 * reads and writes the same parameter object a JSON edit would, and the server checks every save against the
 * type's schema whatever produced it.
 */
export function NodeSettingsForm({
  form,
  schema: raw,
  value,
  steps,
  idPrefix,
  onChange,
  errors,
  hiddenChoices,
  testIds,
}: {
  form: NodeForm;
  schema: Record<string, unknown>;
  value: Params;
  steps: StepRefs;
  idPrefix: string;
  onChange: (next: Params) => void;
  /** The server's check messages by parameter name, each shown under its field. */
  errors?: Record<string, string>;
  /** Choices a select leaves out, by parameter name: those behind a console switch that is off. */
  hiddenChoices?: Record<string, string[]>;
  /** A control's test id, by parameter name. */
  testIds?: Record<string, string>;
}) {
  const schema = raw as Schema;
  const required = new Set(schema.required ?? []);
  return (
    <div className="flex flex-col gap-4" data-testid="node-settings-form">
      {form.order.map((name) => {
        const spec = form.fields[name];
        const declared = schema.properties?.[name] ?? {};
        const hide = hiddenChoices?.[name];
        const field = hide?.length && declared.oneOf ? { ...declared, oneOf: declared.oneOf.filter((o) => o.const === undefined || !hide.includes(String(o.const))) } : declared;
        const id = `${idPrefix}-${name}`;
        return (
          <FormField key={name} id={id} label={spec.label} optional={!required.has(name)} hint={spec.help} error={errors?.[name]}>
            <FieldControl id={id} spec={spec} schema={field} value={value[name]} steps={steps} onChange={(v) => onChange(without(value, name, v))} testId={testIds?.[name]} />
          </FormField>
        );
      })}
    </div>
  );
}

function FieldControl({ id, spec, schema, value, steps, onChange, testId }: { id: string; spec: NodeFormField; schema: Schema; value: unknown; steps: StepRefs; onChange: (v: unknown) => void; testId?: string }) {
  switch (spec.widget) {
    case 'text':
      return <Input id={id} value={typeof value === 'string' ? value : ''} placeholder={spec.placeholder ?? (typeof schema.default === 'string' ? `e.g. ${schema.default}` : undefined)} onChange={(e) => onChange(e.target.value || undefined)} data-field={id} />;
    case 'textarea':
      return <Textarea id={id} value={typeof value === 'string' ? value : ''} rows={4} onChange={(e) => onChange(e.target.value || undefined)} data-field={id} />;
    case 'number':
      return <Input id={id} type="number" inputMode="decimal" value={typeof value === 'number' ? String(value) : ''} onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} data-field={id} />;
    case 'date':
      return <Input id={id} type="date" value={typeof value === 'string' ? value : ''} onChange={(e) => onChange(e.target.value || undefined)} data-field={id} />;
    case 'switch':
      return <Switch id={id} checked={value === true} onCheckedChange={(c) => onChange(c)} />;
    case 'select':
      return <EnumSelect id={id} schema={schema} value={value} onChange={onChange} testId={testId} />;
    case 'source':
      return <SourceSelect id={id} source={spec.source} value={value} steps={steps} onChange={onChange} />;
    case 'mapping':
      return <MappingInput id={id} value={value} steps={steps} onChange={onChange} />;
    case 'mappings':
      return <MappingsInput id={id} value={asObject(value)} steps={steps} onChange={(v) => onChange(Object.keys(v).length ? v : undefined)} />;
    case 'list':
      return spec.item ? <ListInput id={id} item={spec.item} schema={schema.items ?? {}} value={asList(value)} steps={steps} onChange={(v) => onChange(v.length ? v : undefined)} /> : null;
    case 'options':
      return <OptionsInput id={id} value={asList(value)} steps={steps} onChange={(v) => onChange(v.length ? v : undefined)} />;
    case 'json':
      return <JsonInput id={id} value={value} onChange={onChange} />;
  }
}

function EnumSelect({ id, schema, value, onChange, testId }: { id: string; schema: Schema; value: unknown; onChange: (v: unknown) => void; testId?: string }) {
  // A saved value the choices do not list (a path) stays shown as itself.
  const listed = schemaChoices(schema);
  const options = typeof value === 'string' && value && !listed.some((o) => o.value === value) ? [...listed, { value, label: value }] : listed;
  const fallback = schema.default !== undefined ? `Default (${String(schema.default)})` : 'Not set';
  return (
    <Select value={typeof value === 'string' ? value : NONE} onValueChange={(v) => onChange(v === NONE ? undefined : v)}>
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

/** A choice from a platform list (agents, tools, workflows) or from this workflow's own steps. */
function SourceSelect({ id, source, value, steps, onChange }: { id: string; source?: OptionSource; value: unknown; steps: StepRefs; onChange: (v: unknown) => void }) {
  const remote = useEngineOptions(source);
  const options: EngineOption[] = source === 'steps' ? steps.all.map((s) => ({ value: s.id, label: s.label, description: s.type })) : (remote.data ?? []);
  const current = typeof value === 'string' ? value : '';
  // A saved value the list no longer offers stays visible, so opening the form never changes a setting.
  const shown = current && !options.some((o) => o.value === current) ? [...options, { value: current, label: current, description: 'Not in the list' }] : options;
  return (
    <Select value={current || NONE} onValueChange={(v) => onChange(v === NONE ? undefined : v)}>
      <SelectTrigger id={id} className="w-full" data-field={id} aria-busy={remote.isFetching || undefined}>
        <SelectValue placeholder={remote.isPending && source !== 'steps' ? 'Loading…' : 'Choose'} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>Not set</SelectItem>
        {shown.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            <span className="truncate">{o.label}</span>
            {o.description && <span className="ml-2 truncate text-xs text-muted-foreground">{o.description}</span>}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

type Kind = 'path' | 'text' | 'number' | 'boolean';
const KIND_LABEL: Record<Kind, string> = { path: 'Step output', text: 'Text', number: 'Number', boolean: 'Yes or no' };
const kindOf = (v: unknown): Kind => (typeof v === 'number' ? 'number' : typeof v === 'boolean' ? 'boolean' : typeof v === 'string' && v.startsWith('$.') ? 'path' : 'text');

/**
 * One mapped value: a path into the run (`$.input…` or `$.nodes.<step>.out…`), text, a number or yes/no. The kind is
 * stored in the value's own type, and a path is a lookup the runner resolves; no field evaluates code.
 */
export function MappingInput({ id, value, steps, onChange }: { id: string; value: unknown; steps: StepRefs; onChange: (v: unknown) => void }) {
  const [kind, setKind] = React.useState<Kind>(() => kindOf(value));
  React.useEffect(() => {
    if (value !== undefined && value !== '') setKind(kindOf(value));
  }, [value]);
  const roots = [{ value: '$.input', label: 'Run input' }, ...steps.earlier.map((s) => ({ value: `$.nodes.${s.id}.out`, label: s.label }))];
  const text = value === undefined || value === null ? '' : String(value);
  const switchKind = (k: Kind) => {
    setKind(k);
    if (k === 'boolean') onChange(true);
    else if (k === 'number') onChange(Number.isFinite(Number(text)) && text !== '' ? Number(text) : undefined);
    else if (k === 'path') onChange(text.startsWith('$.') ? text : undefined);
    else onChange(text.startsWith('$.') ? undefined : text || undefined);
  };
  return (
    <div className="flex min-w-0 flex-col gap-1.5" data-mapping={id}>
      <div className="flex min-w-0 gap-1.5">
        <Select value={kind} onValueChange={(k) => switchKind(k as Kind)}>
          <SelectTrigger className="w-32 shrink-0" aria-label="Value kind">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(KIND_LABEL) as Kind[]).map((k) => (
              <SelectItem key={k} value={k}>
                {KIND_LABEL[k]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {kind === 'boolean' ? (
          <div className="flex items-center gap-2 px-1">
            <Switch id={id} checked={value === true} onCheckedChange={(c) => onChange(c)} />
            <span className="text-sm text-muted-foreground">{value === true ? 'Yes' : 'No'}</span>
          </div>
        ) : (
          <Input
            id={id}
            className="min-w-0 flex-1 font-mono text-xs"
            inputMode={kind === 'number' ? 'decimal' : undefined}
            value={text}
            placeholder={kind === 'path' ? 'e.g. $.input.amount' : kind === 'number' ? 'e.g. 100' : 'e.g. Refund over limit'}
            onChange={(e) => {
              const v = e.target.value;
              if (kind === 'number') onChange(v === '' ? undefined : Number.isFinite(Number(v)) ? Number(v) : v);
              else onChange(v === '' ? undefined : v);
            }}
            data-field={id}
          />
        )}
      </div>
      {kind === 'path' && (
        <Select value={NONE} onValueChange={(v) => v !== NONE && onChange(v)}>
          <SelectTrigger className="h-8 w-full text-xs" aria-label="Insert a step output">
            <SelectValue placeholder="Insert a step output" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE} disabled>
              Insert a step output
            </SelectItem>
            {roots.map((r) => (
              <SelectItem key={r.value} value={r.value}>
                {r.label} <span className="ml-2 font-mono text-xs text-muted-foreground">{r.value}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}

/** Named values, each a mapping; the names keep the order they were added in. */
function MappingsInput({ id, value, steps, onChange }: { id: string; value: Params; steps: StepRefs; onChange: (v: Params) => void }) {
  const entries = Object.entries(value);
  const rename = (from: string, to: string) => onChange(Object.fromEntries(entries.map(([k, v]) => [k === from ? to : k, v])));
  const add = () => {
    let n = entries.length + 1;
    while (`field${n}` in value) n += 1;
    onChange({ ...value, [`field${n}`]: '' });
  };
  return (
    <div className="flex flex-col gap-2" data-testid={`${id}-rows`}>
      {entries.map(([key, v], i) => (
        <div key={i} className="flex min-w-0 flex-col gap-1.5 rounded-md border p-2">
          <div className="flex items-center gap-1.5">
            <Input aria-label="Name" className="h-8 min-w-0 flex-1 font-mono text-xs" value={key} onChange={(e) => e.target.value && !(e.target.value in value) && rename(key, e.target.value)} />
            <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`Remove ${key}`} onClick={() => onChange(Object.fromEntries(entries.filter(([k]) => k !== key)))}>
              <X />
            </Button>
          </div>
          <MappingInput id={`${id}-${i}`} value={v} steps={steps} onChange={(nv) => onChange({ ...value, [key]: nv ?? '' })} />
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" className="self-start" onClick={add}>
        <Plus /> Add field
      </Button>
    </div>
  );
}

/** A list of objects, each edited with the item form its type declares. */
function ListInput({ id, item, schema, value, steps, onChange }: { id: string; item: NodeForm; schema: Schema; value: unknown[]; steps: StepRefs; onChange: (v: unknown[]) => void }) {
  return (
    <div className="flex flex-col gap-2" data-testid={`${id}-rows`}>
      {value.map((entry, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-md border p-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">{i + 1}</span>
            <Button type="button" variant="ghost" size="icon" className="size-7" aria-label={`Remove ${i + 1}`} onClick={() => onChange(value.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </div>
          <NodeSettingsForm form={item} schema={schema} value={asObject(entry)} steps={steps} idPrefix={`${id}-${i}`} onChange={(next) => onChange(value.map((e, j) => (j === i ? next : e)))} />
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => onChange([...value, {}])}>
        <Plus /> Add
      </Button>
    </div>
  );
}

type ReviewOption = { name: string; label?: string; call?: { node: string }; inputs?: unknown[] };
const toOption = (o: unknown): ReviewOption => (typeof o === 'string' ? { name: o } : { ...(asObject(o) as ReviewOption) });
/** An option with nothing but a name is stored as the name, as the type's schema allows. */
const fromOption = (o: ReviewOption): unknown => (o.label || o.call || o.inputs ? Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== '')) : o.name);

/** A review's options: each is an out port, may carry a label, and may authorise one tool step's write. */
function OptionsInput({ id, value, steps, onChange }: { id: string; value: unknown[]; steps: StepRefs; onChange: (v: unknown[]) => void }) {
  const options = value.map(toOption);
  const tools = steps.all.filter((s) => s.type === 'ops.action.tool');
  const set = (i: number, patch: Partial<ReviewOption>) => onChange(options.map((o, j) => fromOption(j === i ? { ...o, ...patch } : o)));
  return (
    <div className="flex flex-col gap-2" data-testid={`${id}-rows`}>
      {options.map((o, i) => (
        <div key={i} className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-1.5 rounded-md border p-2">
          <Input aria-label="Port name" className="h-8 font-mono text-xs" value={o.name} placeholder="e.g. approve" onChange={(e) => set(i, { name: e.target.value })} />
          <Input aria-label="Label" className="h-8" value={o.label ?? ''} placeholder="e.g. Approve" onChange={(e) => set(i, { label: e.target.value || undefined })} />
          <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`Remove ${o.name || i + 1}`} onClick={() => onChange(options.filter((_, j) => j !== i).map(fromOption))}>
            <X />
          </Button>
          <div className="col-span-3">
            <Select value={o.call?.node ?? NONE} onValueChange={(v) => set(i, { call: v === NONE ? undefined : { node: v } })}>
              <SelectTrigger className="h-8 w-full text-xs" aria-label="Authorises the write of">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>Authorises no write</SelectItem>
                {tools.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    Authorises {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {!!o.inputs?.length && <p className="mt-1 text-xs text-muted-foreground">{o.inputs.length} reviewer inputs, edited in All settings</p>}
          </div>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => onChange([...options.map(fromOption), `option${options.length + 1}`])}>
        <Plus /> Add option
      </Button>
    </div>
  );
}

/** A JSON value the type keeps as a schema of its own (an input or answer schema); a parse error stays in the field. */
function JsonInput({ id, value, onChange }: { id: string; value: unknown; onChange: (v: unknown) => void }) {
  const show = (v: unknown) => (v === undefined ? '' : JSON.stringify(v, null, 2));
  const [text, setText] = React.useState(() => show(value));
  const [error, setError] = React.useState<string>();
  return (
    <div className="flex flex-col gap-1">
      <Textarea
        id={id}
        value={text}
        rows={5}
        spellCheck={false}
        className="font-mono text-xs"
        placeholder='e.g. {"type": "object"}'
        aria-invalid={error ? true : undefined}
        onChange={(e) => {
          setText(e.target.value);
          if (!e.target.value.trim()) {
            setError(undefined);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(e.target.value));
            setError(undefined);
          } catch {
            setError('Not valid JSON yet');
          }
        }}
        data-field={id}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
