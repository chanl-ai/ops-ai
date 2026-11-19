import assert from 'node:assert/strict';
import { test } from 'node:test';

import { toolChange } from './agent-tools.ts';
import type { Agent } from './types/domain.ts';

const stored = (toolIds: string[], switchable: string[]) => ({ toolIds, limits: { switchableToolIds: switchable } }) as unknown as Pick<Agent, 'toolIds' | 'limits'>;

test('a grant or a removal is made on the stored list, so a tool granted since the page was drawn stays', () => {
  // The page showed [lookup]; an @ insert has since granted place_hold. Granting send_letter keeps both.
  assert.deepEqual(toolChange(stored(['lookup', 'place_hold'], []), { add: ['send_letter'] }), { toolIds: ['lookup', 'place_hold', 'send_letter'] });
  // A removed tool leaves the tools callers may switch off, which the service refuses to keep without the grant.
  const removed = toolChange(stored(['lookup', 'place_hold'], ['place_hold']), { remove: ['place_hold'] });
  assert.deepEqual([removed?.toolIds, removed?.limits?.switchableToolIds], [['lookup'], []]);
  // Nothing to change sends nothing.
  assert.equal(toolChange(stored(['lookup'], []), { add: ['lookup'], remove: ['gone'] }), null);
});
