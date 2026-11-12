import assert from 'node:assert/strict';
import { test } from 'node:test';

import { kindsToConnect } from './source-kinds.ts';

const base = { type: 'tool', kind: 'tool', group: 'apps', needsConnection: true, connected: false, plugin: 'salesforce' } as const;

test('an app that is on but not connected keeps its connect link, though create refuses it', () => {
  const missing = { ...base, title: 'Salesforce', canCreate: false, cannotCreateCode: 'connection_missing' };
  assert.deepEqual(kindsToConnect([missing]), [missing]);
});

test('a connection that signs in each person gets no connect link', () => {
  assert.deepEqual(kindsToConnect([{ ...base, title: 'Gmail', canCreate: false, cannotCreateCode: 'sign_in_not_team' }]), []);
});
