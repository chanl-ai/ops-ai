import assert from 'node:assert/strict';
import { test } from 'node:test';

import { chatModelBody, needsModelSetup, providerStep, setupKeyName } from './model-setup.ts';

// A new workspace has no model key, so its first admin is shown the setup before chat fails on them.
test('an account admin of a workspace with no model key is asked to set one up', () => {
  assert.equal(needsModelSetup({ admin: true, keys: [] }), true);
});

// Once a key is saved, or for a member who cannot add one, the overview shows no setup; nothing shows while loading.
test('a workspace with a key, a member, or keys still loading shows no setup', () => {
  assert.equal(needsModelSetup({ admin: true, keys: [{ name: 'OPENAI' }] }), false);
  assert.equal(needsModelSetup({ admin: false, keys: [] }), false);
  assert.equal(needsModelSetup({ admin: true, keys: undefined }), false);
});

// Azure OpenAI is reached at the customer's own resource, so without its endpoint the key cannot be tested or used.
test('Azure OpenAI asks for its endpoint; OpenAI and Anthropic do not', () => {
  assert.equal(providerStep.safeParse({ provider: 'azure-openai', endpoint: '', apiVersion: 'v1' }).success, false);
  assert.equal(providerStep.safeParse({ provider: 'azure-openai', endpoint: 'https://contoso.openai.azure.com', apiVersion: 'v1' }).success, true);
  assert.equal(providerStep.safeParse({ provider: 'openai', endpoint: '', apiVersion: '' }).success, true);
  assert.equal(providerStep.safeParse({ provider: 'anthropic', endpoint: '', apiVersion: '' }).success, true);
});

// The key is saved under one name per provider, so running setup again replaces it instead of adding a second key,
// and the chat model names that same key; Azure's endpoint goes along only for Azure.
test('setup names one key per provider and points chat at it', () => {
  assert.equal(setupKeyName('openai'), setupKeyName('openai'));
  assert.notEqual(setupKeyName('openai'), setupKeyName('anthropic'));
  assert.deepEqual(chatModelBody({ provider: 'openai', endpoint: 'https://x.openai.azure.com', apiVersion: 'v1' }, 'gpt-4.1-mini'), { provider: 'openai', keyName: setupKeyName('openai'), model: 'gpt-4.1-mini' });
  assert.deepEqual(chatModelBody({ provider: 'azure-openai', endpoint: ' https://c.openai.azure.com ', apiVersion: 'v1' }, 'chat-prod'), {
    provider: 'azure-openai',
    keyName: setupKeyName('azure-openai'),
    model: 'chat-prod',
    endpoint: 'https://c.openai.azure.com',
    apiVersion: 'v1',
  });
});
