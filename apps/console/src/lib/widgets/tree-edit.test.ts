// Layout form edits by path, by failure mode: the wrong block removed or moved, a retype that loses a container's
// blocks, and a binding read from a nested pointer the form cannot show.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { TemplateNode } from '../types/widgets';
import { appendChild, bindTo, blankBlock, boundField, moveAt, nodeAt, removeAt, retype } from './tree-edit.ts';

const TREE = {
  type: 'card',
  title: 'Case',
  children: [
    { type: 'text', text: 'a' },
    { type: 'row', children: [{ type: 'badge', text: 'b' }, { type: 'caption', text: 'c' }] },
  ],
} as TemplateNode;

test('remove and move touch only the block at the path', () => {
  assert.deepEqual(removeAt(TREE, [1, 0]).children, [{ type: 'text', text: 'a' }, { type: 'row', children: [{ type: 'caption', text: 'c' }] }]);
  assert.deepEqual(nodeAt(moveAt(TREE, [1, 1], -1), [1, 0]), { type: 'caption', text: 'c' });
  assert.equal(moveAt(TREE, [0], -1), TREE, 'moving the first block up changes nothing');
  assert.equal(TREE.children && (TREE.children as TemplateNode[]).length, 2, 'the input is not mutated');
});

test('a new block appended to a container previews at once', () => {
  const out = appendChild(TREE, [1], blankBlock('metric'));
  assert.deepEqual(nodeAt(out, [1, 2]), { type: 'metric', label: 'Label', value: 0 });
});

test('retyping a container to another container keeps its blocks, and shared fields survive', () => {
  const col = retype(nodeAt(TREE, [1])!, 'column');
  assert.equal(col.type, 'column');
  assert.equal((col.children as TemplateNode[]).length, 2);
  assert.deepEqual(retype({ type: 'text', text: { $bind: '/title' } } as TemplateNode, 'title'), { type: 'title', text: { $bind: '/title' } });
});

test('only a top-level binding is shown as a field', () => {
  assert.equal(boundField({ $bind: '/payee' }), 'payee');
  assert.equal(boundField({ $bind: '/recent/0/amount' }), undefined);
  assert.equal(boundField('payee'), undefined);
  assert.deepEqual(bindTo('a/b'), { $bind: '/a~1b' });
});
