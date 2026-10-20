// A widget's data schema as rows for the fields table (c-110). The table edits name, type, required, description,
// allowed values and default; every other keyword a property carries (maxLength, items, minimum, format) is kept per
// field and written back, so editing in the form never drops a limit set in JSON. Relative imports: the tests run
// under `node --test`, which does not resolve the `@/` alias.
import type { SchemaField, SchemaType } from '../types/tool-modules';

const TYPES = new Set<SchemaType>(['string', 'integer', 'number', 'boolean', 'object', 'array']);
const EDITED = new Set(['type', 'description', 'enum', 'default']);

export interface SchemaRows {
  fields: SchemaField[];
  /** Keywords the table does not edit, by field name. */
  extras: Record<string, Record<string, unknown>>;
  /** Top-level keywords besides `type`, `properties` and `required` (e.g. additionalProperties). */
  rest: Record<string, unknown>;
  /** False when a property's shape cannot be shown as a row (no single type, or a non-string enum); edit in JSON. */
  editable: boolean;
}

export function rowsOfSchema(schema: Record<string, unknown> | undefined): SchemaRows {
  const { type, properties, required, ...rest } = schema ?? {};
  const props = (properties ?? {}) as Record<string, Record<string, unknown>>;
  const req = new Set((required ?? []) as string[]);
  let editable = type === undefined || type === 'object';
  const fields: SchemaField[] = [];
  const extras: SchemaRows['extras'] = {};
  for (const [name, p] of Object.entries(props)) {
    const t = p.type as SchemaType;
    if (!TYPES.has(t)) editable = false;
    if (p.enum !== undefined && !(Array.isArray(p.enum) && p.enum.every((v) => typeof v === 'string'))) editable = false;
    const d = p.default;
    fields.push({
      name,
      type: TYPES.has(t) ? t : 'string',
      required: req.has(name),
      ...(typeof p.description === 'string' ? { description: p.description } : {}),
      ...(Array.isArray(p.enum) ? { enum: p.enum as string[] } : {}),
      ...(typeof d === 'string' || typeof d === 'number' || typeof d === 'boolean' ? { default: d } : {}),
    });
    extras[name] = Object.fromEntries(Object.entries(p).filter(([k]) => !EDITED.has(k)));
  }
  return { fields, extras, rest, editable };
}

/** The schema the rows describe, with each field's kept keywords; a keyword that no longer fits its type is dropped. */
export function schemaOfRows(fields: SchemaField[], extras: SchemaRows['extras'], rest: Record<string, unknown>): Record<string, unknown> {
  const properties: Record<string, Record<string, unknown>> = {};
  for (const f of fields) {
    if (!f.name) continue;
    const kept = { ...(extras[f.name] ?? {}) };
    if (f.type !== 'string') for (const k of ['maxLength', 'minLength', 'pattern', 'format']) delete kept[k];
    if (f.type !== 'array') delete kept.items;
    properties[f.name] = {
      ...kept,
      type: f.type,
      ...(f.description ? { description: f.description } : {}),
      ...(f.enum?.length ? { enum: f.enum } : {}),
      ...(f.default !== undefined ? { default: f.default } : {}),
    };
  }
  const required = fields.filter((f) => f.name && f.required).map((f) => f.name);
  return { type: 'object', ...rest, properties, ...(required.length ? { required } : {}) };
}
