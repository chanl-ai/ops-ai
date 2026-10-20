// The authoring preview's fill, by failure mode: a binding left unreplaced, a tone lookup ignored, and a node whose
// optional data is missing drawn empty instead of dropped.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { fillTemplate, pointer } from './bind.ts';
import type { TemplateNode } from '../types/widgets';

const TREE = {
  type: 'card',
  title: { $bind: '/payee' },
  children: [
    { type: 'badge', text: { $bind: '/status' }, tones: { held: 'warning' } },
    { type: 'table', rows: { $bind: '/recent' } },
    { type: 'keyValue', items: [{ label: 'Account', value: { $bind: '/account' } }] },
  ],
} as TemplateNode;

test('every binding is replaced from the data, by JSON Pointer', () => {
  const out = fillTemplate(TREE, { payee: 'Acme', status: 'held', account: 'CHQ-2219', recent: [{ a: 1 }] });
  assert.deepEqual(out, {
    type: 'card',
    title: 'Acme',
    children: [
      { type: 'badge', text: 'held', tone: 'warning' },
      { type: 'table', rows: [{ a: 1 }] },
      { type: 'keyValue', items: [{ label: 'Account', value: 'CHQ-2219' }] },
    ],
  });
});

test('a node whose required data is missing is dropped', () => {
  const out = fillTemplate(TREE, { payee: 'Acme', status: 'held', account: 'x' });
  assert.equal(out?.type === 'card' && out.children.some((c) => c.type === 'table'), false);
});

test('pointers read arrays and escaped keys', () => {
  assert.equal(pointer({ a: [{ 'b/c': 3 }] }, '/a/0/b~1c'), 3);
  assert.equal(pointer({ a: 1 }, '/missing'), undefined);
});
