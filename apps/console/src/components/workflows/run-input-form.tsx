'use client';

import * as React from 'react';

import { NodeSettingsForm } from '@/components/workflows/definition-editor/node-form';
import { EntityPicker } from '@/components/shared/entity-picker';
import { FileUpload } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { fileOptions } from '@/hooks/options-queries';
import type { NodeForm, NodeFormField } from '@/lib/types/engine';

type Schema = { type?: string | string[]; format?: string; enum?: unknown[]; title?: string; description?: string; properties?: Record<string, Schema>; required?: string[]; items?: Schema; default?: unknown };
type FileRef = { fileId: string; name?: string };

// A run's input refers to no earlier step, so the form offers none.
const NO_STEPS = { all: [], earlier: [] };

/** A file input: an object naming a `fileId` (one file) or a list of them (several), as the trigger's schema declares. */
function fileShape(s: Schema): 'one' | 'many' | null {
  const isFile = (x?: Schema) => !!x && (x.format === 'file' || (x.type === 'object' && !!x.properties?.fileId));
  if (isFile(s)) return 'one';
  if (s.type === 'array' && isFile(s.items)) return 'many';
  return null;
}

/** The settings form's widget for a schema field, or null when only JSON can say it. */
function widgetFor(s: Schema): NodeFormField['widget'] | null {
  if (s.enum?.length) return 'select';
  if (s.type === 'string') return s.format === 'date' ? 'date' : 'text';
  if (s.type === 'number' || s.type === 'integer') return 'number';
  if (s.type === 'boolean') return 'switch';
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
export function RunInputForm({ schema: raw, value, onChange, error }: { schema: Record<string, unknown>; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; error?: string }) {
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
    fields: Object.fromEntries(simple.map(([n, field]) => [n, { label: label(n, field), widget: widgetFor(field)!, help: field.description }])),
  };
  const files = props.filter(([, field]) => fileShape(field));
  const rest = props.filter(([, field]) => !fileShape(field) && !widgetFor(field));

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
        {files.map(([name, field]) => {
          const many = fileShape(field) === 'many';
          const current: FileRef[] = many ? ((value[name] as FileRef[] | undefined) ?? []) : value[name] ? [value[name] as FileRef] : [];
          const set = (next: FileRef[]) => onChange({ ...value, [name]: many ? next : next[0] });
          return (
            <FormField key={name} id={`run-${name}`} label={label(name, field)} optional={!required.has(name)} hint={field.description ?? (many ? 'Upload files or pick ones already in Files.' : 'Upload a file or pick one already in Files.')}>
              <div className="flex flex-col gap-2" data-testid={`run-files-${name}`}>
                <FileUpload
                  id={`run-${name}-upload`}
                  purpose="case_attachment"
                  multiple={many}
                  testId={`run-files-${name}-upload`}
                  onChange={(items) => {
                    const uploaded = items.filter((i) => i.fileId).map((i) => ({ fileId: i.fileId!, name: i.name }));
                    const picked = current.filter((f) => !items.some((i) => i.fileId === f.fileId));
                    if (uploaded.length) set([...picked, ...uploaded.filter((u) => !picked.some((p) => p.fileId === u.fileId))]);
                  }}
                />
                <EntityPicker
                  source={fileOptions}
                  multiple={many}
                  value={current.map((f) => f.fileId)}
                  onChange={(ids) => set(ids.map((id) => current.find((f) => f.fileId === id) ?? { fileId: id }))}
                  addLabel={many ? 'Pick files from Files' : 'Pick a file from Files'}
                  searchPlaceholder="Search files"
                  testId={`run-files-${name}-pick`}
                />
              </div>
            </FormField>
          );
        })}
        {simple.length > 0 && <NodeSettingsForm form={form} schema={schema as Record<string, unknown>} value={value} steps={NO_STEPS} idPrefix="run" onChange={(v) => onChange(v as Record<string, unknown>)} />}
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
