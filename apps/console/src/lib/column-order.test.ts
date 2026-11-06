import assert from 'node:assert/strict';
import { test } from 'node:test';

import { idLast } from './column-order.ts';

test('the record id sits after every data column and before the row actions, whatever order a page lists them', () => {
  assert.deepEqual(idLast(['select', 'recordId', 'name', 'team', 'actions']), ['select', 'name', 'team', 'recordId', 'actions']);
  // A viewer's table has no select box and no actions menu: the id still comes last, not first.
  assert.deepEqual(idLast(['recordId', 'name', 'team']), ['name', 'team', 'recordId']);
  assert.deepEqual(idLast(['name', 'team']), ['name', 'team']);
});
