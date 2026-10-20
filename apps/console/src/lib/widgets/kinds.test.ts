import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';

import { pickRenderer } from '../../components/chat/widget-registry.ts';
import type { WidgetPart } from '../types/widgets.ts';
import { toKind } from './kinds.ts';

const schemas = JSON.parse(readFileSync(new URL('./kinds.schema.json', import.meta.url), 'utf8')) as Record<string, { required: string[]; properties: Record<string, unknown> }>;
const samples = JSON.parse(readFileSync(new URL('./kind-samples.json', import.meta.url), 'utf8')) as Record<string, { industry: string; data: Record<string, unknown> }[]>;
const parts = JSON.parse(readFileSync(new URL('./sample-parts.json', import.meta.url), 'utf8')) as WidgetPart[];

test('every shape still draws once the shape renderers are gone: each converts to a kind', () => {
  const drawn = parts.map((p) => toKind(pickRenderer(p), p.hint).type);
  assert.deepEqual(new Set(drawn), new Set(['chart', 'table', 'entity', 'metric', 'form', 'confirm', 'tracker']));
});

test('each converted kind has the fields its schema requires', () => {
  for (const p of parts) {
    const node = toKind(pickRenderer(p), p.hint) as unknown as Record<string, unknown>;
    const missing = schemas[String(node.type)].required.filter((f) => node[f] === undefined);
    assert.deepEqual(missing, [], `${p.id} as ${String(node.type)}`);
  }
});

test('the gallery shows every kind the kernel knows, each in two industries, with only fields its schema names', () => {
  assert.deepEqual(Object.keys(samples).sort(), Object.keys(schemas).sort());
  for (const [kind, list] of Object.entries(samples)) {
    assert.ok(new Set(list.map((s) => s.industry)).size >= 2, `${kind} shows one industry`);
    for (const s of list) {
      const unknown = Object.keys(s.data).filter((k) => !(k in schemas[kind].properties));
      assert.deepEqual(unknown, [], `${kind} ${s.industry}`);
    }
  }
});
