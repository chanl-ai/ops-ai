import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { WidgetPart } from '../../lib/types/widgets.ts';
import { pickRenderer, renderersFor } from './widget-registry.ts';

const rows: WidgetPart = { type: 'widget', id: 'w1', shape: 'rows', data: [{ month: 'Jan', opened: 3 }, { month: 'Feb', opened: 5 }] };
const names: WidgetPart = { type: 'widget', id: 'w2', shape: 'rows', data: [{ name: 'Ada', team: 'Ops' }] };
const series: WidgetPart = { type: 'widget', id: 'w3', shape: 'series', data: { x: ['Jan'], series: [{ name: 'opened', y: [3] }] }, hint: { x: 'month' } };

test('each shape draws with its default renderer', () => {
  const ids = (['rows', 'series', 'record', 'metric', 'form', 'decision', 'steps'] as const).map((shape) => {
    const data = { rows: [{ a: 'x' }], series: { x: [], series: [] }, record: { a: 1 }, metric: { value: 1, label: 'n' }, form: { schema: { type: 'object', properties: {} } }, decision: { summary: '', action: '', args: {}, holdId: 'h' }, steps: [] }[shape];
    return pickRenderer({ type: 'widget', id: shape, shape, data } as WidgetPart).id;
  });
  assert.deepEqual(ids, ['table', 'line', 'fields', 'stat', 'form', 'confirmation', 'task']);
});

test('rows that can be charted offer the charts with converted data', () => {
  const options = renderersFor(rows);
  assert.deepEqual(options.map((o) => o.id), ['table', 'line', 'bar', 'area']);
  assert.deepEqual(options[1].data, { x: ['Jan', 'Feb'], series: [{ name: 'opened', y: [3, 5] }] });
});

test('rows that cannot be charted offer only the table', () => {
  assert.deepEqual(renderersFor(names).map((o) => o.id), ['table']);
});

test("a valid hint's prefer wins over the default; an invalid one is ignored", () => {
  assert.equal(pickRenderer({ ...rows, hint: { prefer: 'bar' } } as WidgetPart).id, 'bar');
  assert.equal(pickRenderer({ ...names, hint: { prefer: 'bar' } } as WidgetPart).id, 'table');
  assert.equal(pickRenderer({ ...rows, hint: { prefer: 'stat' } } as WidgetPart).id, 'table');
});

test("the person's choice wins over the hint when it can draw the part", () => {
  assert.equal(pickRenderer({ ...rows, hint: { prefer: 'bar' } } as WidgetPart, 'table').id, 'table');
  assert.equal(pickRenderer(names, 'line').id, 'table');
});

test('a series switched to a table gets rows keyed by the hint x', () => {
  assert.deepEqual(pickRenderer(series, 'table').data, [{ month: 'Jan', opened: 3 }]);
});
