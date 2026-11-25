import assert from 'node:assert/strict';
import { test } from 'node:test';

import { without } from './schema-values.ts';
import { aliasWriteAccess, connectionBody, knobProblems, settingsForAlias } from './model-forms.ts';
import type { KnobSchema, ProviderTypeInfo } from './types/models.ts';

const secret = { type: 'string', 'x-secret': true } as const;
const BEDROCK: ProviderTypeInfo = {
  id: 'bedrock',
  label: 'Amazon Bedrock',
  icon: 'aws',
  listsModels: true,
  catalogued: true,
  connection: { type: 'object', properties: { region: { type: 'string', 'x-column': 'region' }, accessKeyId: secret, secretAccessKey: secret }, required: ['region', 'accessKeyId', 'secretAccessKey'] },
};
const COMPATIBLE: ProviderTypeInfo = {
  id: 'openai-compatible',
  label: 'OpenAI-compatible URL',
  icon: 'plug',
  listsModels: true,
  catalogued: false,
  connection: { type: 'object', properties: { baseUrl: { type: 'string', 'x-column': 'base_url' }, apiKey: secret }, required: ['baseUrl'] },
};

// models-service seals only `secrets` and refuses a secret field it was sent as a column, so a key sent any other way
// would be stored as plain text or refused.
test('a connection sends its secret fields only in secrets and its column fields at the top', () => {
  const body = connectionBody(BEDROCK, 'bedrock-lending', { region: 'us-east-1', accessKeyId: 'AKIA1', secretAccessKey: 'shh' });
  assert.deepEqual(body, { name: 'bedrock-lending', type: 'bedrock', region: 'us-east-1', secrets: { accessKeyId: 'AKIA1', secretAccessKey: 'shh' }, keyRef: 'BEDROCK-LENDING' });
});

// An endpoint that takes no key must not send secrets: the service refuses secrets without a keyRef and a keyRef
// without a saved key leaves the connection signing in with nothing.
test('a connection given no key sends neither secrets nor a key name', () => {
  const body = connectionBody(COMPATIBLE, 'plant-vllm', { baseUrl: 'https://llm.example.com/v1' });
  assert.deepEqual(body, { name: 'plant-vllm', type: 'openai-compatible', baseUrl: 'https://llm.example.com/v1' });
});

const KNOBS: Record<string, KnobSchema> = {
  temperature: { type: 'number', minimum: 0, maximum: 2, default: 1 },
  max_tokens: { type: 'integer', minimum: 1, default: 16384 },
};

// The agent save is refused (422 model_setting_invalid) for a number outside the model's range, so the dialog says so
// before it sends.
test('a setting outside its model range is named, and a setting inside it is not', () => {
  assert.deepEqual(knobProblems(KNOBS, { temperature: 5, max_tokens: 100 }), { temperature: 'At most 2.' });
  assert.deepEqual(knobProblems(KNOBS, { temperature: 0.2, max_tokens: 1.5 }), { max_tokens: 'A whole number.' });
});

// Moving an agent to a model that takes no temperature must not keep the temperature it had: the service refuses the
// whole save for one knob its model does not take.
test('an agent moved to another alias keeps only the settings the new model takes', () => {
  assert.deepEqual(settingsForAlias({ max_tokens: KNOBS.max_tokens }, { temperature: 0.3, max_tokens: 2000 }), { max_tokens: 2000 });
});

// Reset puts a knob back to the catalog default by leaving its key out; sending the default as a value would pin it
// when the catalog default later moves.
test('resetting a setting removes its key instead of storing the default', () => {
  assert.deepEqual(without({ temperature: 0.3, max_tokens: 2000 }, 'temperature', undefined), { max_tokens: 2000 });
});

// Alias writes need install.manage (the workspace owner); an admin without it must see the aliases with the reason and
// no way to start a write that models-service would refuse.
test('someone without install.manage sees aliases read only with the reason', () => {
  assert.deepEqual(aliasWriteAccess(true), { editable: true, reason: null });
  const viewer = aliasWriteAccess(false);
  assert.equal(viewer.editable, false);
  assert.match(String(viewer.reason), /Only the workspace owner changes model aliases/);
});
