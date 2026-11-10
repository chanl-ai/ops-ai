import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createdRowsReducer, withCreatedRows, type CreatedEntry } from './created-rows.ts';

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

const shown = (rows: Row[], at = 100) => rows.reduce<CreatedEntry<Row>[]>((s, row) => createdRowsReducer(s, { type: 'show', row, at }), []);
const written = (state: CreatedEntry<Row>[], variables: unknown, submittedAt = 200) =>
  createdRowsReducer(state, { type: 'written', write: { variables, submittedAt }, idOf: id });

test('a created row the person then removes is no longer shown', () => {
  const state = shown([{ id: 'z', v: 0 }]);
  assert.deepEqual(written(state, 'z').map((e) => e.row.id), []);
});

test('a bulk remove, or a write sent with the id in a field, unpins each row it names and keeps the others', () => {
  const state = shown([{ id: 'x', v: 0 }, { id: 'y', v: 0 }, { id: 'z', v: 0 }]);
  assert.deepEqual(written(state, ['x', 'q']).map((e) => e.row.id), ['z', 'y']);
  assert.deepEqual(written(state, { kind: 'host', value: 'y' }).map((e) => e.row.id), ['z', 'x']);
  assert.deepEqual(written(state, { ids: ['z'], patch: { sla: 4 } }).map((e) => e.row.id), ['y', 'x']);
});

test('the add that created the row does not unpin it: a write sent before the row was shown is ignored', () => {
  const state = shown([{ id: 'z', v: 0 }], 100);
  assert.equal(written(state, { value: 'z', note: '' }, 90), state);
});

test('a write that names no created row leaves the rows as they are', () => {
  const state = shown([{ id: 'z', v: 0 }]);
  assert.equal(written(state, { value: 'other', note: 'z.example' }), state);
});
