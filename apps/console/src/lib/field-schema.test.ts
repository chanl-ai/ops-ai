import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { KindField } from './connect-plan.ts';
import { fieldErrors, schemaForFields } from './field-schema.ts';

const field = (f: Partial<KindField> & { name: string }): KindField => ({ label: f.name, secret: false, required: false, advanced: false, ...f });

test('an empty required field gets its error and a filled one none', () => {
  const schema = schemaForFields([field({ name: 'clientId', label: 'Client ID', required: true }), field({ name: 'note' })]);
  assert.deepEqual(fieldErrors(schema.safeParse({ clientId: ' ', note: '' })), { clientId: 'Enter the client ID.' });
  assert.deepEqual(fieldErrors(schema.safeParse({ clientId: 'abc', note: '' })), {});
});

test('a field required only when another holds a value follows that value', () => {
  const schema = schemaForFields([field({ name: 'mode' }), field({ name: 'password', label: 'Password', requiredWhen: { mode: 'basic' } })]);
  assert.deepEqual(fieldErrors(schema.safeParse({ mode: 'basic', password: '' })), { password: 'Enter the password.' });
  assert.deepEqual(fieldErrors(schema.safeParse({ mode: 'bearer', password: '' })), {});
});

test('PEM text must start as PEM does', () => {
  const schema = schemaForFields([field({ name: 'cert', label: 'Certificate', pem: true })]);
  assert.match(fieldErrors(schema.safeParse({ cert: 'not a cert' })).cert ?? '', /PEM/);
  assert.deepEqual(fieldErrors(schema.safeParse({ cert: '-----BEGIN CERTIFICATE-----\nx' })), {});
});
