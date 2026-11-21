import assert from 'node:assert/strict';
import { test } from 'node:test';

import { keptEdits, keptEditsByGroup } from './kept-edits.ts';

test('after someone else saves, the fields a person changed stay and the rest take the newer copy', () => {
  const read = { name: 'Refund', steps: [{ do: 'Look up' }], when: 'A refund is asked for' };
  const edited = { ...read, steps: [{ do: 'Look up the charge' }] };
  const newer = { ...read, name: 'Refund a charge', when: 'A card refund is asked for' };
  assert.deepEqual(keptEdits(read, edited, newer), { name: 'Refund a charge', steps: [{ do: 'Look up the charge' }], when: 'A card refund is asked for' });
  // With nothing edited, the newer copy is shown as it is.
  assert.deepEqual(keptEdits(read, read, newer), newer);
});

test('a group of settings is carried setting by setting, so each person keeps the limit they changed', () => {
  const read = { name: 'Card desk', limits: { callersMayAddInstructions: false, allowedModels: ['fast'], budget: { ceilingUsd: 2 } } };
  // He raised the budget; she has since let callers add instructions and allowed a second model.
  const edited = { ...read, limits: { ...read.limits, budget: { ceilingUsd: 5 } } };
  const newer = { ...read, limits: { ...read.limits, callersMayAddInstructions: true, allowedModels: ['fast', 'deep'] } };
  assert.deepEqual(keptEditsByGroup(read, edited, newer), { name: 'Card desk', limits: { callersMayAddInstructions: true, allowedModels: ['fast', 'deep'], budget: { ceilingUsd: 5 } } });
});
