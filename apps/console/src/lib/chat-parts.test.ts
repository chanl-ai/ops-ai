import assert from 'node:assert/strict';
import { test } from 'node:test';

import { withPart } from './chat-parts.ts';
import type { WidgetPart } from './types/widgets';

const plan = (state: 'running' | 'done'): WidgetPart =>
  ({ type: 'widget', id: 'wp_plan', shape: 'steps', data: [{ title: 'Read the loan files', state }] }) as WidgetPart;
const table = { type: 'widget', id: 'wp_c1', shape: 'rows', data: [{ id: 'L-1' }] } as WidgetPart;

test('a part with an id the reply holds is redrawn in place, so a plan update never stacks a second checklist', () => {
  const parts = withPart(withPart(withPart(undefined, plan('running')), table), plan('done'));
  assert.deepEqual(parts.map((p) => p.id), ['wp_plan', 'wp_c1']);
  assert.equal((parts[0] as { data: { state: string }[] }).data[0].state, 'done');
});

test('a part with a new id is added after the rest', () => {
  assert.deepEqual(withPart([table], plan('running')).map((p) => p.id), ['wp_c1', 'wp_plan']);
});
