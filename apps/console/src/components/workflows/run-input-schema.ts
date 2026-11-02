/** A trigger start form's JSON Schema as a sample payload and a field guide for the JSON tab. */

export type SchemaField = {
  type?: string | string[];
  format?: string;
  title?: string;
  description?: string;
  examples?: unknown[];
  enum?: unknown[];
  oneOf?: { const?: unknown; title?: string }[];
  default?: unknown;
  properties?: Record<string, SchemaField>;
  required?: string[];
  items?: SchemaField;
};

export type FieldGuide = { key: string; label: string; type: string; example: string };

const words = (name: string, field: SchemaField) =>
  field.title ??
  name
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .toLowerCase()
    .replace(/\bid\b/g, 'ID')
    .replace(/^\w/, (c) => c.toUpperCase());

const typeName = (field: SchemaField): string => {
  if (field.format === 'file') return 'file';
  if (field.format === 'email') return 'email';
  if (field.format === 'date') return 'date';
  if (field.enum?.length || field.oneOf?.some((o) => o.const !== undefined)) return 'choice';
  const t = field.type;
  if (Array.isArray(t)) return t.filter((x) => x !== 'null').join(' | ') || 'any';
  return t || 'any';
};

const exampleValue = (field: SchemaField): unknown => {
  if (field.examples?.length) return field.examples[0];
  if (field.default !== undefined) return field.default;
  if (field.enum?.length) return field.enum[0];
  const choice = field.oneOf?.find((o) => o.const !== undefined);
  if (choice) return choice.const;
  const t = typeName(field);
  if (t === 'file') return '';
  if (t === 'number' || t === 'integer') return 0;
  if (t === 'boolean') return false;
  if (t === 'array') return [];
  if (t === 'object') return {};
  return '';
};

const show = (value: unknown): string => {
  if (value === undefined || value === null || value === '') return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
};

export const isEmptyInput = (value: Record<string, unknown>): boolean =>
  Object.values(value).every((v) => v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length));

/** One object the JSON tab can show: each property's example, else its default, else a typed blank. */
export function sampleFromSchema(raw: Record<string, unknown>): Record<string, unknown> {
  const schema = raw as SchemaField;
  return Object.fromEntries(Object.entries(schema.properties ?? {}).map(([key, field]) => [key, exampleValue(field)]));
}

/** Field name, type and example for the JSON tab, in schema order. */
export function fieldGuide(raw: Record<string, unknown>): FieldGuide[] {
  const schema = raw as SchemaField;
  return Object.entries(schema.properties ?? {}).map(([key, field]) => ({
    key,
    label: words(key, field),
    type: typeName(field),
    example: show(exampleValue(field)),
  }));
}
