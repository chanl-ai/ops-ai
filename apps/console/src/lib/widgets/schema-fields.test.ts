// The widget fields table's schema round trip, by failure mode: a limit set in JSON dropped by a form edit, a keyword
// left on a field whose type no longer takes it, and a schema the table cannot show offered for editing anyway.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { rowsOfSchema, schemaOfRows } from './schema-fields.ts';

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['caseId'],
  properties: {
    caseId: { type: 'string', maxLength: 40 },
    status: { type: 'string', enum: ['open', 'closed'] },
    recent: { type: 'array', items: { type: 'object' } },
  },
};

test('an untouched round trip gives back the same schema, limits and all', () => {
  const r = rowsOfSchema(SCHEMA);
  assert.equal(r.editable, true);
  assert.deepEqual(schemaOfRows(r.fields, r.extras, r.rest), SCHEMA);
});

test('adding a field keeps every other field’s limits and additionalProperties', () => {
  const r = rowsOfSchema(SCHEMA);
  const out = schemaOfRows([...r.fields, { name: 'region', type: 'string', required: false }], r.extras, r.rest);
  assert.equal(out.additionalProperties, false);
  assert.deepEqual((out.properties as Record<string, unknown>).caseId, { type: 'string', maxLength: 40 });
  assert.deepEqual((out.properties as Record<string, unknown>).region, { type: 'string' });
});

test('a type change drops the keywords the new type does not take', () => {
  const r = rowsOfSchema(SCHEMA);
  const fields = r.fields.map((f) => (f.name === 'caseId' ? { ...f, type: 'number' as const } : f.name === 'recent' ? { ...f, type: 'string' as const } : f));
  const props = schemaOfRows(fields, r.extras, r.rest).properties as Record<string, Record<string, unknown>>;
  assert.deepEqual(props.caseId, { type: 'number' });
  assert.deepEqual(props.recent, { type: 'string' });
});

test('a property with no single type is not offered in the table', () => {
  assert.equal(rowsOfSchema({ type: 'object', properties: { v: { type: ['string', 'null'] } } }).editable, false);
  assert.equal(rowsOfSchema({ type: 'object', properties: { v: { type: 'integer', enum: [1, 2] } } }).editable, false);
});
