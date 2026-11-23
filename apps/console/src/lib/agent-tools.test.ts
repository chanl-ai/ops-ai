import assert from 'node:assert/strict';
import { test } from 'node:test';

import { knowledgeChange, listChange, toolChange } from './agent-tools.ts';
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

test('a knowledge base picked on the page is added to the stored list, so one inserted since the page was drawn stays', () => {
  const held = (collections: string[], allowed: string[]) => ({ collections, limits: { allowedKnowledgeBaseIds: allowed } }) as unknown as Pick<Agent, 'collections' | 'limits'>;
  // The page showed [kb_cards] and the person picked kb_loans; an @ insert has since added kb_fees to the stored list.
  const change = listChange(['kb_cards'], ['kb_cards', 'kb_loans']);
  const saved = knowledgeChange(held(['kb_cards', 'kb_fees'], ['kb_cards', 'kb_fees']), change);
  assert.deepEqual([saved?.collections, saved?.limits?.allowedKnowledgeBaseIds], [['kb_cards', 'kb_fees', 'kb_loans'], ['kb_loans', 'kb_cards', 'kb_fees']]);
});
