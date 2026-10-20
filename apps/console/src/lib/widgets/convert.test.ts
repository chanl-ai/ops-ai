import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { Rows } from '../types/widgets.ts';
import { recordToRows, rowsToSeries, seriesToRows } from './convert.ts';

const monthly = [
  { month: 'Jan', opened: 12, closed: 9, owner: 'Ops' },
  { month: 'Feb', opened: 15, closed: 14, owner: 'Ops' },
];

test('rows with a text key and numeric keys become a series over that key', () => {
  assert.deepEqual(rowsToSeries(monthly), { x: ['Jan', 'Feb'], series: [{ name: 'opened', y: [12, 15] }, { name: 'closed', y: [9, 14] }] });
});

test("the hint's x and y pick the axis and the lines", () => {
  const rows = [{ day: 1, label: 'a', amount: 5, fee: 1 }, { day: 2, label: 'b', amount: 7, fee: 2 }];
  assert.deepEqual(rowsToSeries(rows, { x: 'day', y: ['fee'] }), { x: [1, 2], series: [{ name: 'fee', y: [1, 2] }] });
});

test('a hint naming a missing or non-numeric key falls back to inference', () => {
  assert.deepEqual(rowsToSeries(monthly, { x: 'nope', y: ['owner'] })?.series.map((s) => s.name), ['opened', 'closed']);
});

test('rows with no numeric key, no label key, or no rows cannot be a chart', () => {
  assert.equal(rowsToSeries([{ name: 'a', team: 'b' }]), null);
  assert.equal(rowsToSeries([{ a: 1, b: 2 }]), null);
  assert.equal(rowsToSeries([]), null);
});

test('a key missing from one row is not used as a line', () => {
  const rows: Rows = [{ m: 'Jan', a: 1, b: 2 }, { m: 'Feb', a: 3 }];
  assert.deepEqual(rowsToSeries(rows)?.series.map((s) => s.name), ['a']);
});

test('series to rows and back is lossless', () => {
  const s = rowsToSeries(monthly)!;
  const rows = seriesToRows(s, 'month');
  assert.deepEqual(rows, [{ month: 'Jan', opened: 12, closed: 9 }, { month: 'Feb', opened: 15, closed: 14 }]);
  assert.deepEqual(rowsToSeries(rows), s);
});

test('a record becomes field and value rows in its order', () => {
  assert.deepEqual(recordToRows({ Account: 'CHQ-2219', Balance: 1200, Frozen: false }), [
    { Field: 'Account', Value: 'CHQ-2219' },
    { Field: 'Balance', Value: 1200 },
    { Field: 'Frozen', Value: false },
  ]);
});
