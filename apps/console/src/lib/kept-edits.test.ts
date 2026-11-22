import assert from 'node:assert/strict';
import { test } from 'node:test';

import { keptEdits } from './kept-edits.ts';

test('after someone else saves, the fields a person changed stay and the rest take the newer copy', () => {
  const read = { name: 'Refund', steps: [{ do: 'Look up' }], when: 'A refund is asked for' };
  const edited = { ...read, steps: [{ do: 'Look up the charge' }] };
  const newer = { ...read, name: 'Refund a charge', when: 'A card refund is asked for' };
  assert.deepEqual(keptEdits(read, edited, newer), { name: 'Refund a charge', steps: [{ do: 'Look up the charge' }], when: 'A card refund is asked for' });
  // With nothing edited, the newer copy is shown as it is.
  assert.deepEqual(keptEdits(read, read, newer), newer);
});
