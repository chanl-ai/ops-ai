'use client';

import * as React from 'react';
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react';

import { AddMenu } from '@/components/shared/add-menu';
import { FormField } from '@/components/shared/form-field';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { TemplateNode } from '@/lib/types/widgets';
import { appendChild, bindTo, blankBlock, type BlockType, boundField, CONTAINERS, moveAt, type NodePath, removeAt, retype, updateAt } from '@/lib/widgets/tree-edit';

const BLOCKS: { type: BlockType; label: string }[] = [
  { type: 'card', label: 'Card' },
  { type: 'row', label: 'Row' },
  { type: 'column', label: 'Column' },
  { type: 'title', label: 'Title' },
  { type: 'text', label: 'Text' },
  { type: 'caption', label: 'Caption' },
  { type: 'badge', label: 'Badge' },
  { type: 'metric', label: 'Metric' },
  { type: 'keyValue', label: 'Label and value list' },
  { type: 'table', label: 'Table' },
  { type: 'chart', label: 'Chart' },
  { type: 'list', label: 'List' },
  { type: 'button', label: 'Button' },
  { type: 'divider', label: 'Divider' },
];
const LABEL = Object.fromEntries(BLOCKS.map((b) => [b.type, b.label])) as Record<string, string>;
const TONES = ['neutral', 'info', 'success', 'warning', 'danger'];
const FORMATS = ['text', 'number', 'money', 'date', 'percent'];
const FIXED = '__fixed';

interface Fields {
  /** Every top-level data field, for text and value bindings. */
  all: string[];
  /** Array fields, the only ones a table, chart or list can draw rows from. */
  lists: string[];
}

/** A block's value: fixed text, or taken from one of the data's fields (`{ "$bind": "/field" }`). */
function ValueInput({ id, label, value, fields, onChange, numeric }: { id: string; label: string; value: unknown; fields: string[]; onChange: (v: unknown) => void; numeric?: boolean }) {
  const field = boundField(value);
  const fixed = value === undefined || value === null ? '' : typeof value === 'object' ? '' : String(value);
  return (
    <FormField id={id} label={label}>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Select value={field ?? FIXED} onValueChange={(v) => onChange(v === FIXED ? (numeric ? 0 : '') : bindTo(v))}>
          <SelectTrigger className="w-full sm:w-44" aria-label={`${label} source`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={FIXED}>Fixed value</SelectItem>
            {fields.map((f) => (
              <SelectItem key={f} value={f}>
                From {f}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {field === undefined && (
          <Input id={id} type={numeric ? 'number' : 'text'} value={fixed} onChange={(e) => onChange(numeric ? (e.target.value === '' ? undefined : Number(e.target.value)) : e.target.value)} className="flex-1" />
        )}
      </div>
    </FormField>
  );
}

/** The data field a table, chart or list draws its rows from. */
function ListSource({ id, value, lists, onChange }: { id: string; value: unknown; lists: string[]; onChange: (v: unknown) => void }) {
  const field = boundField(value);
  return (
    <FormField id={id} label="Rows from" hint={lists.length ? undefined : 'Add a field of type array in Data first.'}>
      <Select value={field ?? ''} onValueChange={(v) => onChange(bindTo(v))} disabled={!lists.length}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue placeholder="Choose a list field" />
        </SelectTrigger>
        <SelectContent>
          {lists.map((f) => (
            <SelectItem key={f} value={f}>
              {f}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

function Choice({ id, label, value, options, onChange }: { id: string; label: string; value: string | undefined; options: string[]; onChange: (v: string) => void }) {
  return (
    <FormField id={id} label={label}>
      <Select value={value ?? ''} onValueChange={onChange}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue placeholder="Default" />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

/** Rows of small inputs under one heading (table columns, label and value items, badge tones), with add and remove. */
function RowList<T>({ title, rows, render, blank, onChange, noun }: { title: string; rows: T[]; render: (row: T, set: (r: T) => void, i: number) => React.ReactNode; blank: T; onChange: (rows: T[]) => void; noun: string }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium">{title}</span>
      {rows.map((r, i) => (
        <div key={i} className="flex flex-col gap-2 sm:flex-row sm:items-end">
          {render(r, (next) => onChange(rows.map((x, n) => (n === i ? next : x))), i)}
          <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${noun} ${i + 1}`} onClick={() => onChange(rows.filter((_, n) => n !== i))}>
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}
      <div>
        <Button type="button" variant="outline" size="sm" onClick={() => onChange([...rows, blank])}>
          <Plus className="size-4" /> Add {noun}
        </Button>
      </div>
    </div>
  );
}

function Props({ node, id, fields, set }: { node: TemplateNode; id: string; fields: Fields; set: (patch: Record<string, unknown>) => void }) {
  const v = (k: string) => node[k];
  switch (node.type) {
    case 'card':
      return <ValueInput id={`${id}-title`} label="Title" value={v('title')} fields={fields.all} onChange={(x) => set({ title: x })} />;
    case 'row':
    case 'column':
      return (
        <div className="grid gap-4 sm:grid-cols-2">
          <Choice id={`${id}-gap`} label="Gap" value={v('gap') as string} options={['sm', 'md', 'lg']} onChange={(x) => set({ gap: x })} />
          <Choice id={`${id}-align`} label="Align" value={v('align') as string} options={['start', 'center', 'end', 'between']} onChange={(x) => set({ align: x })} />
        </div>
      );
    case 'title':
    case 'text':
    case 'caption':
      return <ValueInput id={`${id}-text`} label="Text" value={v('text')} fields={fields.all} onChange={(x) => set({ text: x })} />;
    case 'badge': {
      const tones = Object.entries((v('tones') ?? {}) as Record<string, string>);
      return (
        <div className="flex flex-col gap-4">
          <ValueInput id={`${id}-text`} label="Text" value={v('text')} fields={fields.all} onChange={(x) => set({ text: x })} />
          <Choice id={`${id}-tone`} label="Tone" value={v('tone') as string} options={TONES} onChange={(x) => set({ tone: x })} />
          <RowList
            title="Tone for a value"
            noun="tone"
            rows={tones}
            blank={['', 'neutral'] as [string, string]}
            onChange={(rows) => set({ tones: rows.length ? Object.fromEntries(rows) : undefined })}
            render={([value, tone], put, i) => (
              <>
                <Input aria-label={`Tone ${i + 1} value`} value={value} onChange={(e) => put([e.target.value, tone])} placeholder="e.g. held" className="flex-1" />
                <Select value={tone} onValueChange={(t) => put([value, t])}>
                  <SelectTrigger className="w-full sm:w-36" aria-label={`Tone ${i + 1}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TONES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            )}
          />
        </div>
      );
    }
    case 'metric':
      return (
        <div className="grid gap-4 sm:grid-cols-2">
          <ValueInput id={`${id}-label`} label="Label" value={v('label')} fields={fields.all} onChange={(x) => set({ label: x })} />
          <ValueInput id={`${id}-value`} label="Value" value={v('value')} fields={fields.all} onChange={(x) => set({ value: x })} />
          <ValueInput id={`${id}-unit`} label="Unit" value={v('unit')} fields={fields.all} onChange={(x) => set({ unit: x })} />
          <ValueInput id={`${id}-delta`} label="Change" value={v('delta')} fields={fields.all} onChange={(x) => set({ delta: x })} numeric />
        </div>
      );
    case 'keyValue':
      return (
        <RowList
          title="Items"
          noun="item"
          rows={(v('items') ?? []) as { label: unknown; value: unknown }[]}
          blank={{ label: 'Label', value: '' }}
          onChange={(rows) => set({ items: rows })}
          render={(r, put, i) => (
            <div className="grid flex-1 gap-2 sm:grid-cols-2">
              <ValueInput id={`${id}-item-${i}-label`} label={`Item ${i + 1} label`} value={r.label} fields={fields.all} onChange={(x) => put({ ...r, label: x })} />
              <ValueInput id={`${id}-item-${i}-value`} label={`Item ${i + 1} value`} value={r.value} fields={fields.all} onChange={(x) => put({ ...r, value: x })} />
            </div>
          )}
        />
      );
    case 'table':
      return (
        <div className="flex flex-col gap-4">
          <ListSource id={`${id}-rows`} value={v('rows')} lists={fields.lists} onChange={(x) => set({ rows: x })} />
          <RowList
            title="Columns"
            noun="column"
            rows={(v('columns') ?? []) as { key: string; label?: string; format?: string }[]}
            blank={{ key: '', label: '' }}
            onChange={(rows) => set({ columns: rows })}
            render={(c, put, i) => (
              <>
                <Input aria-label={`Column ${i + 1} key`} value={c.key} onChange={(e) => put({ ...c, key: e.target.value })} placeholder="Key in each row" className="flex-1 font-mono text-xs" />
                <Input aria-label={`Column ${i + 1} heading`} value={c.label ?? ''} onChange={(e) => put({ ...c, label: e.target.value || undefined })} placeholder="Heading" className="flex-1" />
                <Select value={c.format ?? 'text'} onValueChange={(f) => put({ ...c, format: f })}>
                  <SelectTrigger className="w-full sm:w-32" aria-label={`Column ${i + 1} format`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FORMATS.map((f) => (
                      <SelectItem key={f} value={f}>
                        {f}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            )}
          />
        </div>
      );
    case 'chart':
      return (
        <div className="grid gap-4 sm:grid-cols-2">
          <ListSource id={`${id}-rows`} value={v('rows')} lists={fields.lists} onChange={(x) => set({ rows: x })} />
          <Choice id={`${id}-kind`} label="Kind" value={v('kind') as string} options={['line', 'bar', 'area']} onChange={(x) => set({ kind: x })} />
          <FormField id={`${id}-x`} label="X axis key">
            <Input id={`${id}-x`} value={String(v('x') ?? '')} onChange={(e) => set({ x: e.target.value })} className="font-mono text-xs" />
          </FormField>
          <FormField id={`${id}-y`} label="Series keys" hint="Comma-separated keys in each row.">
            <Input id={`${id}-y`} value={((v('y') ?? []) as string[]).join(', ')} onChange={(e) => set({ y: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} className="font-mono text-xs" />
          </FormField>
        </div>
      );
    case 'list':
      return <ListSource id={`${id}-items`} value={v('items')} lists={fields.lists} onChange={(x) => set({ items: x })} />;
    case 'button': {
      const reply = (v('reply') ?? {}) as { text?: string; values?: Record<string, unknown> };
      return (
        <div className="grid gap-4 sm:grid-cols-2">
          <ValueInput id={`${id}-label`} label="Label" value={v('label')} fields={fields.all} onChange={(x) => set({ label: x })} />
          <FormField id={`${id}-reply`} label="Message it sends" hint="Sent to the agent as the person's next message.">
            <Input id={`${id}-reply`} value={reply.text ?? ''} onChange={(e) => set({ reply: { ...reply, text: e.target.value } })} />
          </FormField>
        </div>
      );
    }
    default:
      return null;
  }
}

function TypeSelect({ value, onChange, label }: { value: string; onChange: (t: BlockType) => void; label: string }) {
  return (
    <Select value={value} onValueChange={(t) => onChange(t as BlockType)}>
      <SelectTrigger className="h-8 w-44" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {BLOCKS.map((b) => (
          <SelectItem key={b.type} value={b.type}>
            {b.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function Block({ root, path, fields, onChange }: { root: TemplateNode; path: NodePath; fields: Fields; onChange: (t: TemplateNode) => void }) {
  let node: TemplateNode = root;
  for (const i of path) node = (node.children as TemplateNode[])[i];
  const id = `block-${path.join('-') || 'root'}`;
  const name = path.length ? `Block ${path.map((i) => i + 1).join('.')}` : 'Top block';
  const index = path[path.length - 1] ?? 0;
  const siblings = path.length ? ((path.slice(0, -1).reduce<TemplateNode>((n, i) => (n.children as TemplateNode[])[i], root).children as TemplateNode[]) ?? []).length : 1;
  const children = (node.children ?? []) as TemplateNode[];
  const set = (patch: Record<string, unknown>) => onChange(updateAt(root, path, (n) => Object.fromEntries(Object.entries({ ...n, ...patch }).filter(([, x]) => x !== undefined)) as TemplateNode));
  return (
    <Card className="gap-3 py-3 shadow-none" data-testid="layout-block" data-path={path.join('.')}>
      <CardHeader className="flex flex-row flex-wrap items-center gap-2 px-3">
        <span className="text-xs text-muted-foreground">{name}</span>
        <TypeSelect value={String(node.type)} label={`${name} type`} onChange={(t) => onChange(updateAt(root, path, (n) => retype(n, t)))} />
        {path.length > 0 && (
          <div className="ml-auto flex gap-1">
            <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`Move ${name} up`} disabled={index === 0} onClick={() => onChange(moveAt(root, path, -1))}>
              <ArrowUp className="size-4" />
            </Button>
            <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`Move ${name} down`} disabled={index >= siblings - 1} onClick={() => onChange(moveAt(root, path, 1))}>
              <ArrowDown className="size-4" />
            </Button>
            <Button type="button" variant="ghost" size="icon" className="size-8" aria-label={`Remove ${name}`} onClick={() => onChange(removeAt(root, path))}>
              <Trash2 className="size-4" />
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-3">
        <Props node={node} id={id} fields={fields} set={set} />
        {CONTAINERS.has(node.type) && (
          <div className="flex flex-col gap-3 border-l pl-3">
            {children.map((_, i) => (
              <Block key={i} root={root} path={[...path, i]} fields={fields} onChange={onChange} />
            ))}
            <AddMenu label="Add a block" ariaLabel={`Add a block to ${name}`} items={BLOCKS.map((b) => ({ value: b.type, label: b.label }))} onSelect={(t) => onChange(appendChild(root, path, blankBlock(t as BlockType)))} className="w-44" />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * A widget's layout as nested blocks from the catalogue the kernel accepts (ops_agent_kernel.layout). Each field holds
 * a fixed value or takes one from the data; tables, charts and lists draw from a list field. Fields the form does not
 * show (a button's reply values, nested bindings) are kept as they are and edited in the JSON view, as is an image
 * block, which the chat always draws blocked (chat-widgets).
 */
export function LayoutEditor({ tree, onChange, fields }: { tree: TemplateNode; onChange: (t: TemplateNode) => void; fields: Fields }) {
  return (
    <div className="flex flex-col gap-3" data-testid="layout-editor">
      <Block root={tree} path={[]} fields={fields} onChange={onChange} />
      <p className="text-xs text-muted-foreground">{LABEL[String(tree.type)] ? 'Blocks draw top to bottom; rows lay theirs side by side.' : 'This block type is edited in the JSON view.'}</p>
    </div>
  );
}
