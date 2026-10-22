'use client';

import * as React from 'react';

import { NodeSettingsForm, schemaChoices } from '@/components/workflows/definition-editor/node-form';
import { type FileRef, FileRefsField } from '@/components/shared/file-refs-field';
import { FormField } from '@/components/shared/form-field';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import type { OptionSource } from '@/hooks/options-queries';
import type { NodeForm, NodeFormField } from '@/lib/types/engine';

type Schema = { type?: string | string[]; format?: string; 'x-widget'?: string; examples?: unknown[]; enum?: unknown[]; oneOf?: { const?: unknown; title?: string }[]; title?: string; description?: string; properties?: Record<string, Schema>; required?: string[]; items?: Schema; default?: unknown };

// A run's input refers to no earlier step, so the form offers none.
const NO_STEPS = { all: [], earlier: [] };

/**
 * A file input, as the trigger's schema declares it: a string with `format: "file"` holds one file's id, an object
 * naming a `fileId` (or with `format: "file"`) holds one file, and a list of those holds several.
 */
export function fileShape(s: Schema): 'id' | 'one' | 'many' | null {
  const isFile = (x?: Schema) => !!x && (x.format === 'file' || (x.type === 'object' && !!x.properties?.fileId));
  if (s.type === 'string' && s.format === 'file') return 'id';
  if (isFile(s)) return 'one';
  if (s.type === 'array' && isFile(s.items)) return 'many';
  return null;
}

/**
 * The run input with `file` put in the schema's first file field: the bare id for a string, `{ fileId, name }` for an
 * object, a list for an array. Unchanged when the schema has no file field.
 */
export function withFile(schema: Record<string, unknown>, value: Record<string, unknown>, file: FileRef): Record<string, unknown> {
  const first = Object.entries((schema as Schema).properties ?? {}).find(([, f]) => fileShape(f));
  if (!first) return value;
  const shape = fileShape(first[1]);
  return { ...value, [first[0]]: shape === 'id' ? file.fileId : shape === 'many' ? [file] : file };
}

/** The settings form's widget for a schema field, or null when only JSON can say it. */
function widgetFor(field: Schema): NodeFormField['widget'] | null {
  if (schemaChoices(field).length) return 'select';
  if (field.type === 'string') return field.format === 'date' ? 'date' : field['x-widget'] === 'textarea' ? 'textarea' : 'text';
  if (field.type === 'number' || field.type === 'integer') return 'number';
  if (field.type === 'boolean') return 'switch';
  return null;
}

// A field the schema gives no title is named from its key in words: "fileId" → "File ID", "customer_name" → "Customer name".
const label = (name: string, s: Schema) =>
  s.title ??
  name
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .toLowerCase()
    .replace(/\bid\b/g, 'ID')
    .replace(/^\w/, (c) => c.toUpperCase());

/**
 * The run's input as a form generated from the trigger's input schema: text, number, money, date, choice and yes or no
 * with the settings form's own controls, and file inputs that upload or pick files (stored in Files first; the run gets
 * their ids). A JSON tab edits the same value for anything the form cannot say.
 */
export function RunInputForm({ schema: raw, value, onChange, error, fileSource }: { schema: Record<string, unknown>; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; error?: string; fileSource?: OptionSource }) {
  const schema = raw as Schema;
  const props = Object.entries(schema.properties ?? {});
  const required = new Set(schema.required ?? []);
  const [tab, setTab] = React.useState<'form' | 'json'>('form');
  const [text, setText] = React.useState(() => JSON.stringify(value, null, 2));
  const [jsonError, setJsonError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (tab === 'form') setText(JSON.stringify(value, null, 2));
  }, [value, tab]);

  const simple = props.filter(([, field]) => !fileShape(field) && widgetFor(field));
  const form: NodeForm = {
    order: simple.map(([n]) => n),
    fields: Object.fromEntries(simple.map(([n, field]) => [n, { label: label(n, field), widget: widgetFor(field)!, help: field.description, placeholder: typeof field.examples?.[0] === 'string' ? `e.g. ${field.examples[0]}` : undefined }])),
  };
  const rest = props.filter(([, field]) => !fileShape(field) && !widgetFor(field));
  // Fields draw in the schema's order: each file field on its own, the plain fields between them as one settings form.
  const groups: ({ file: string } | { plain: string[] })[] = [];
  for (const [name, field] of props) {
    const last = groups[groups.length - 1];
    if (fileShape(field)) groups.push({ file: name });
    else if (widgetFor(field)) {
      if (last && 'plain' in last) last.plain.push(name);
      else groups.push({ plain: [name] });
    }
  }
  const fileField = (name: string, field: Schema) => {
    const shape = fileShape(field);
    const many = shape === 'many';
    const held = value[name];
    const current: FileRef[] = many ? ((held as FileRef[] | undefined) ?? []) : typeof held === 'string' && held ? [{ fileId: held }] : held && typeof held === 'object' ? [held as FileRef] : [];
    // A string field gets the id alone, which is what a workflow reading `$.input.<name>` as an id expects.
    const set = (next: FileRef[]) => onChange({ ...value, [name]: many ? next : shape === 'id' ? next[0]?.fileId : next[0] });
    return (
      <FormField key={name} id={`run-${name}`} label={label(name, field)} optional={!required.has(name)} hint={field.description ?? (many ? 'Upload files or pick ones already in Files.' : 'Upload a file or pick one already in Files.')}>
        <FileRefsField id={`run-${name}`} many={many} value={current} onChange={set} testId={`run-files-${name}`} source={fileSource} />
      </FormField>
    );
  };

  return (
    <Tabs value={tab} onValueChange={(t) => setTab(t as 'form' | 'json')} className="gap-3">
      <TabsList>
        <TabsTrigger value="form" data-testid="run-input-form-tab">
          Form
        </TabsTrigger>
        <TabsTrigger value="json" data-testid="run-input-json-tab">
          JSON
        </TabsTrigger>
      </TabsList>
      <TabsContent value="form" className="flex flex-col gap-4" data-testid="run-input-form">
        {groups.map((g) =>
          'file' in g ? (
            fileField(g.file, schema.properties![g.file])
          ) : (
            <NodeSettingsForm key={g.plain.join(',')} form={{ ...form, order: g.plain }} schema={schema as Record<string, unknown>} value={value} steps={NO_STEPS} idPrefix="run" onChange={(v) => onChange(v as Record<string, unknown>)} />
          ),
        )}
        {rest.length > 0 && <p className="text-xs text-muted-foreground">{rest.map(([n, field]) => label(n, field)).join(', ')} {rest.length === 1 ? 'takes' : 'take'} JSON: use the JSON tab.</p>}
        {props.length === 0 && <p className="text-sm text-muted-foreground">This trigger declares no inputs; the JSON tab sends any object.</p>}
      </TabsContent>
      <TabsContent value="json">
        <FormField id="run-input-json" label="Input" hint="The same input as the form, as JSON." error={jsonError ?? error}>
          <Textarea
            id="run-input-json"
            value={text}
            rows={10}
            spellCheck={false}
            className="font-mono text-xs"
            data-testid="definition-run-input"
            onChange={(e) => {
              setText(e.target.value);
              try {
                const parsed = e.target.value.trim() ? JSON.parse(e.target.value) : {};
                if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Input must be a JSON object');
                setJsonError(null);
                onChange(parsed as Record<string, unknown>);
              } catch (err) {
                setJsonError(err instanceof Error ? err.message : 'Not valid JSON');
              }
            }}
          />
        </FormField>
      </TabsContent>
    </Tabs>
  );
}
