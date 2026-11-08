import assert from 'node:assert/strict';
import { test } from 'node:test';

import { foldedLine, orderReply } from './reply-order.ts';

type Call = { id: string; name: string; server: string; card?: boolean };
const call = (id: string, name: string, card = false): Call => ({ id, name, server: 'Salesforce', card });
const isCard = (c: Call) => !!c.card;

test('a planned reply leads with its checklist, folds its calls into one line and hides skill loads', () => {
  // A reply drew three loud call rows above the checklist that listed the same steps, and a "Load skill" row.
  const calls = [call('c0', 'load_skill'), call('c1', 'salesforce_query'), call('c2', 'salesforce_query')];
  const out = orderReply(calls, [{ id: 'wp_c2' }, { id: 'wp_plan' }], isCard);
  assert.equal(out.plan?.id, 'wp_plan');
  assert.deepEqual(out.folded.map((c) => c.id), ['c1', 'c2']);
  assert.deepEqual(out.shown, []);
  assert.deepEqual(out.parts.map((p) => p.id), ['wp_c2']);
  assert.equal(foldedLine(out.folded), '2 steps · Salesforce');
});

test('without a plan one call keeps its row, two or more fold, and a card always shows', () => {
  const one = orderReply([call('c1', 'salesforce_query')], [], isCard);
  assert.deepEqual([one.folded.length, one.shown.map((c) => c.id)], [0, ['c1']]);
  const two = orderReply([call('c1', 'salesforce_query'), call('c2', 'salesforce_get_record'), call('c3', 'connect', true)], [], isCard);
  assert.deepEqual([two.folded.map((c) => c.id), two.shown.map((c) => c.id)], [['c1', 'c2'], ['c3']]);
});
