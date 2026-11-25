'use client';

import * as React from 'react';
import { Plus, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useEngineOptions } from '@/hooks/engine-queries';
import { AccountSelect } from '@/components/connections/account-select';
import { JsonInput } from '@/components/shared/json-input';

import { SchemaForm, asList, asObject, schemaChoices, NONE, type FieldContext, type FieldRenderer, type Schema } from '@/components/shared/schema-form';
import type { EngineOption, NodeForm, NodeFormField, OptionSource } from '@/lib/types/engine';

export { schemaChoices };

type Params = Record<string, unknown>;

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

/** The widgets only a workflow step has: a step or platform pick, a mapped value, review options, raw JSON, an account. */
const nodeRenderers = (steps: StepRefs): Record<string, FieldRenderer> => ({
  source: ({ id, spec, value, onChange }: FieldContext) => <SourceSelect id={id} source={(spec as NodeFormField).source} value={value} steps={steps} onChange={onChange} />,
  mapping: ({ id, value, onChange }) => <MappingInput id={id} value={value} steps={steps} onChange={onChange} />,
  mappings: ({ id, value, onChange }) => <MappingsInput id={id} value={asObject(value)} steps={steps} onChange={(v) => onChange(Object.keys(v).length ? v : undefined)} />,
  options: ({ id, value, onChange }) => <OptionsInput id={id} value={asList(value)} steps={steps} onChange={(v) => onChange(v.length ? v : undefined)} />,
  json: ({ id, value, onChange }) => <JsonInput id={id} value={value} onChange={onChange} />,
  account: ({ id, value, onChange }) => <AccountSelect id={id} value={asObject(value)} onChange={(v) => onChange(Object.keys(v).length ? v : undefined)} />,
});

/**
 * A node's settings as the form its type declares (`ui`): the shared schema form with the widgets only a step has.
 * The form reads and writes the same parameter object a JSON edit would, and the server checks every save against
 * the type's schema whatever produced it.
 */
export function NodeSettingsForm({
  form,
  schema,
  value,
  steps,
  idPrefix,
  onChange,
  errors,
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
  /** A control's test id, by parameter name. */
  testIds?: Record<string, string>;
}) {
  const renderers = React.useMemo(() => nodeRenderers(steps), [steps]);
  return <SchemaForm schema={schema as Schema} form={form} value={value} idPrefix={idPrefix} onChange={onChange} errors={errors} testIds={testIds} renderers={renderers} testId="node-settings-form" />;
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
        <SelectValue placeholder={remote.isLoading ? 'Loading…' : 'Choose'} />
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
            className="min-w-0 flex-1 font-mono"
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
          <SelectTrigger className="w-full" aria-label="Insert a step output">
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
            <Input aria-label="Name" className="min-w-0 flex-1 font-mono" value={key} onChange={(e) => e.target.value && !(e.target.value in value) && rename(key, e.target.value)} />
            <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${key}`} onClick={() => onChange(Object.fromEntries(entries.filter(([k]) => k !== key)))}>
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
          <Input aria-label="Port name" className="font-mono" value={o.name} placeholder="e.g. approve" onChange={(e) => set(i, { name: e.target.value })} />
          <Input aria-label="Label" value={o.label ?? ''} placeholder="e.g. Approve" onChange={(e) => set(i, { label: e.target.value || undefined })} />
          <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${o.name || i + 1}`} onClick={() => onChange(options.filter((_, j) => j !== i).map(fromOption))}>
            <X />
          </Button>
          <div className="col-span-3">
            <Select value={o.call?.node ?? NONE} onValueChange={(v) => set(i, { call: v === NONE ? undefined : { node: v } })}>
              <SelectTrigger className="w-full" aria-label="Authorises the write of">
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
