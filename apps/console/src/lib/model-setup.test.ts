import assert from 'node:assert/strict';
import { test } from 'node:test';

import { needsModelSetup } from './model-setup.ts';

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
