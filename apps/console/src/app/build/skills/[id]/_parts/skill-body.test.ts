// A skill with parts used to open a parts editor and a Markdown box in place of the instructions editor.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { skillBody } from './skill-body.ts';

test('a skill that has parts opens on the instructions editor, its parts read-only', () => {
  const part = { slug: 'refund', name: 'Refund', useWhen: 'a refund is asked for', instructions: 'Check the order.', inputs: [], toolIds: [] };
  const body = skillBody({ parts: [part] });
  assert.equal(body.field, 'instructions');
  assert.deepEqual(body.parts, [part]);
  assert.equal(skillBody({ parts: [] }).field, 'text');
});
