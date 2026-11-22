// The skill page saves itself, so a change must survive the save landing and a reload after someone else saved first.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { carriedAfterSave, canSend, type AutosaveState } from './autosave.ts';

const idle: AutosaveState = { waiting: '{"text":"b"}', enabled: true, paused: false, saving: false, stale: null, failed: null };

test('text typed while a save is in flight is still on the page when the saved version arrives', () => {
  const sent = { name: 'Refunds', text: 'step one' };
  const typedSince = { name: 'Refunds', text: 'step one\nstep two' };
  const arrived = { name: 'Refunds', text: 'step one' };
  assert.deepEqual(carriedAfterSave(sent, typedSince, arrived), typedSince);
});

test('nothing is carried when nothing was typed since the save was sent', () => {
  const sent = { name: 'Refunds', text: 'step one' };
  assert.equal(carriedAfterSave(sent, { ...sent }, { ...sent, name: 'Refunds v2' }), null);
});

test('a change refused as stale is sent again after the reload, and not before', () => {
  assert.equal(canSend({ ...idle, stale: 'Dana saved v4 a minute ago.' }), false);
  assert.equal(canSend({ ...idle, paused: true }), false);
  assert.equal(canSend(idle), true);
});

test('a change that failed is not retried until it changes', () => {
  assert.equal(canSend({ ...idle, failed: idle.waiting }), false);
  assert.equal(canSend({ ...idle, failed: '{"text":"a"}' }), true);
});
