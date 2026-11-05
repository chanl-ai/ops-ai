import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { KindField } from './connect-plan.ts';
import { type ConfigField, configSchema, fieldErrors, schemaForFields } from './field-schema.ts';

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

const place: ConfigField = {
  name: 'login_url',
  label: 'Where do you sign in',
  default: 'https://login.salesforce.com',
  choices: [
    { value: 'https://login.salesforce.com', label: 'Production' },
    { value: 'https://test.salesforce.com', label: 'Sandbox' },
  ],
  other: { label: "Your company's address", value: 'https://{host}', hosts: ['.my.salesforce.com'] },
};

test('a config field takes one of its choices or a company address under an allowed host', () => {
  const schema = configSchema([place]);
  assert.equal(schema.safeParse({ login_url: 'https://test.salesforce.com' }).success, true);
  assert.equal(schema.safeParse({ login_url: 'https://acme.my.salesforce.com' }).success, true);
});

test('a config field refuses an address outside its choices and hosts, naming them in a sentence', () => {
  const out = configSchema([place]).safeParse({ login_url: 'https://evil.example.com' });
  assert.equal(out.success, false);
  assert.equal(fieldErrors(out).login_url, "Choose Production, Sandbox or your company's address ending in .my.salesforce.com.");
  // The bare suffix is no company's address.
  assert.equal(configSchema([place]).safeParse({ login_url: 'https://.my.salesforce.com' }).success, false);
});

test('a required config field left empty asks for it', () => {
  const out = configSchema([{ name: 'tenant', label: 'Directory tenant', required: true }]).safeParse({ tenant: ' ' });
  assert.equal(fieldErrors(out).tenant, 'Enter directory tenant.');
});
