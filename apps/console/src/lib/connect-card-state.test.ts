import assert from 'node:assert/strict';
import { test } from 'node:test';

import { connectCardState } from './connect-card-state.ts';

test('a person signed in to another account of the app still gets Connect for the account the call named', () => {
  // Mine reads the app as connected through their first account; the call named a second, which they have not.
  assert.equal(connectCardState({ reason: 'not_connected', linked: false, connectedNow: false }), 'needs_sign_in');
  assert.equal(connectCardState({ reason: 'not_connected', linked: true, connectedNow: false }), 'connected');
});

test('more access or a refused sign-in is settled only by connecting again', () => {
  assert.equal(connectCardState({ reason: 'insufficient_scope', linked: true, connectedNow: false }), 'needs_sign_in');
  assert.equal(connectCardState({ reason: 'refused', linked: true, connectedNow: false }), 'needs_sign_in');
  assert.equal(connectCardState({ reason: 'refused', linked: true, connectedNow: true }), 'connected');
});
