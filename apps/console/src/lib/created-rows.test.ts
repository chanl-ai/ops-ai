import assert from 'node:assert/strict';
import { test } from 'node:test';

import { withCreatedRows } from './created-rows.ts';

type Row = { id: string; v: number };
const id = (r: Row) => r.id;
const page: Row[] = [
  { id: 'a', v: 1 },
  { id: 'b', v: 1 },
];

test('a created row that is not on the page shows first and is pinned', () => {
  const r = withCreatedRows(page, [{ id: 'z', v: 0 }], id);
  assert.deepEqual(r.rows.map(id), ['z', 'a', 'b']);
  assert.deepEqual(r.pinned, ['z']);
});

test('a created row the refetched page also holds shows once, as the page returned it', () => {
  const r = withCreatedRows(page, [{ id: 'b', v: 0 }], id);
  assert.deepEqual(r.rows, [{ id: 'b', v: 1 }, { id: 'a', v: 1 }]);
  assert.deepEqual(r.pinned, ['b']);
});

test('with nothing created the page is unchanged and nothing is pinned', () => {
  const r = withCreatedRows(page, [], id);
  assert.equal(r.rows, page);
  assert.deepEqual(r.pinned, []);
});

test('created rows keep newest first, and a row created twice shows once in its newest place', () => {
  const r = withCreatedRows(page, [{ id: 'y', v: 0 }, { id: 'x', v: 2 }, { id: 'y', v: 9 }], id);
  assert.deepEqual(r.rows.map(id), ['y', 'x', 'a', 'b']);
  assert.deepEqual(r.rows[0], { id: 'y', v: 0 });
});
