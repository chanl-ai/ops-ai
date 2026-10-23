// The workflow layout (c-486), by failure mode: steps that touch or overlap, lines from one step crossing at it because
// ports were ignored, a cycle or a disconnected step breaking the layout, a step added by API sitting on the trigger,
// placed steps moving, the baked seeds going stale, ELK failing on an unknown type, and a large workflow too slow.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import type { EngineDefinition, EngineNodeType } from '@/lib/types/engine';

import { applyLayout, definitionGraph, layoutDefinition, overlapping, placeDefinition, unplacedSteps } from './definition-layout.ts';
import { COLUMN_GAP, type Layout, ROW_GAP, rowFallback } from './layout.ts';
import { fiftySteps, OFF_ORIGIN_SEEDS } from './layout.fixtures.ts';

const ROOT = new URL('../../../../../../', import.meta.url);
const read = (path: string) => JSON.parse(readFileSync(new URL(path, ROOT), 'utf8'));
const TYPES: EngineNodeType[] = read('apps/console/src/components/workflows/layout/node-types.json');
const SEEDS: EngineDefinition[] = [...read('services/agents-service/seed/engine_workflows.json'), read('scripts/demo/workflows/card_dispute_intake.json')];
const seed = (id: string) => structuredClone(SEEDS.find((s) => s.id === id)!);

type Rect = { id: string; x: number; y: number; w: number; h: number };

function rects(def: EngineDefinition, positions?: Layout['positions']): Rect[] {
  const boxes = definitionGraph(def, TYPES).nodes;
  return def.nodes.map((n, i) => {
    const p = positions?.[n.id] ?? n.position ?? { x: 0, y: 0 };
    return { id: n.id, x: p.x, y: p.y, w: boxes[i].width, h: boxes[i].height };
  });
}

/** Pairs closer than the gaps the layout promises: a column apart sideways, or a row apart in one column. */
function crowded(rs: Rect[], column = COLUMN_GAP, row = ROW_GAP): string[] {
  const out: string[] = [];
  for (let i = 0; i < rs.length; i++)
    for (let j = i + 1; j < rs.length; j++) {
      const a = rs[i];
      const b = rs[j];
      const sideways = Math.max(b.x - (a.x + a.w), a.x - (b.x + b.w));
      const down = Math.max(b.y - (a.y + a.h), a.y - (b.y + b.h));
      if (sideways < column - 1 && down < row - 1) out.push(`${a.id}/${b.id}`);
    }
  return out;
}

test('no two steps intersect, with the configured gaps, on every seed', async () => {
  assert.equal(SEEDS.length, 12);
  for (const def of SEEDS) {
    const laid = await layoutDefinition(def, TYPES);
    assert.deepEqual(crowded(rects(def, laid.positions)), [], def.id);
    assert.deepEqual(laid.positions[def.nodes[0].id], { x: 0, y: 0 }, `${def.id}: the first step sits at the origin`);
  }
});

test('targets a step reaches from different ports are ordered by port', async () => {
  let pairs = 0;
  for (const def of SEEDS) {
    const laid = (await layoutDefinition(def, TYPES)).positions;
    const graph = definitionGraph(def, TYPES);
    const incoming = new Map<string, number>();
    for (const c of def.connections) incoming.set(c.to.node, (incoming.get(c.to.node) ?? 0) + 1);
    for (const box of graph.nodes) {
      const order = box.outPorts.map((p) => p.name);
      const sole = def.connections.filter((c) => c.from.node === box.id && incoming.get(c.to.node) === 1);
      for (const a of sole)
        for (const b of sole) {
          if (order.indexOf(a.from.port) >= order.indexOf(b.from.port) || a.to.node === b.to.node) continue;
          if (laid[a.to.node].x !== laid[b.to.node].x) continue;
          pairs++;
          assert.ok(laid[a.to.node].y < laid[b.to.node].y, `${def.id}: ${box.id}.${a.from.port} lands below ${b.from.port}`);
        }
    }
  }
  assert.ok(pairs >= 5, `only ${pairs} port pairs checked`);
});

test('a cycle terminates with every step placed and the first step in the first column', async () => {
  for (const def of [fiftySteps(), seed('mail_intake')]) {
    const laid = await layoutDefinition(def, TYPES);
    assert.equal(Object.keys(laid.positions).length, def.nodes.length, def.id);
    assert.equal(Math.min(...Object.values(laid.positions).map((p) => p.x)), 0, `${def.id}: nothing left of the first step`);
    assert.deepEqual(crowded(rects(def, laid.positions)), [], def.id);
  }
});

test('a disconnected step gets its own place in the first column', async () => {
  const def = seed('levy_case');
  def.nodes.push({ id: 'loose', type: 'ops.data.set', typeVersion: 1, name: 'Loose', parameters: { values: {} } });
  const laid = await layoutDefinition(def, TYPES);
  assert.equal(laid.positions.loose.x, 0);
  assert.deepEqual(crowded(rects(def, laid.positions)), []);
});

async function addedAtOrigin(def: EngineDefinition, label: string) {
  assert.equal(await placeDefinition(def, TYPES), def, `${label}: a placed definition comes back as the same object`);
  const added = { ...def, nodes: [...def.nodes, { id: 'added', type: 'ops.data.set', typeVersion: 1, name: 'Added', position: { x: 0, y: 0 } }] };
  assert.deepEqual([...unplacedSteps(added)], ['added'], label);
  const placed = await placeDefinition(added, TYPES);
  for (const n of def.nodes) assert.deepEqual(placed.nodes.find((m) => m.id === n.id)!.position, n.position, `${label}: ${n.id} moved`);
  const rs = rects(placed);
  const right = Math.max(...rs.filter((r) => r.id !== 'added').map((r) => r.x + r.w));
  assert.equal(rs.find((r) => r.id === 'added')!.x, right + COLUMN_GAP, label);
  assert.deepEqual(crowded(rs, 1, 1).filter((p) => p.includes('added')), [], label);
}

test('the missing-position rule holds on every seed, as stored and as it stood before the bake', async () => {
  for (const def of SEEDS) await addedAtOrigin(def, def.id);
  for (const [id, at] of Object.entries(OFF_ORIGIN_SEEDS)) {
    const def = seed(id);
    // The snapshots were placed for a 240 px step; spread out so they do not overlap at today's size, which would lay
    // them out whole and leave the missing-position rule untested.
    def.nodes = def.nodes.filter((n) => at[n.id]).map((n) => ({ ...n, position: { x: at[n.id][0] * 3, y: at[n.id][1] * 3 } }));
    assert.notDeepEqual(def.nodes[0].position, { x: 0, y: 0 }, `${id}: the snapshot's trigger is off the origin`);
    await addedAtOrigin(def, `${id} before the bake`);
  }
});

test('a step on the exact spot of a non-first earlier step is the only one unplaced', () => {
  const def = seed('levy_case');
  def.nodes[2] = { ...def.nodes[2], position: { ...def.nodes[1].position! } };
  assert.deepEqual([...unplacedSteps(def)], [def.nodes[2].id]);
});

test('a workflow saved with positions for a smaller step is laid out again, and one that fits is left alone', async () => {
  // card_dispute_intake as staging stored it: steps 240 px apart along the main row, so 288 px steps overlap.
  const old = seed('card_dispute_intake');
  old.nodes = old.nodes.map((n, i) => ({ ...n, position: { x: i * 240, y: 0 } }));
  assert.equal(overlapping(old, TYPES), true);
  const placed = await placeDefinition(old, TYPES);
  assert.deepEqual(crowded(rects(placed)), []);
  const fits = seed('card_dispute_intake');
  assert.equal(overlapping(fits, TYPES), false);
  assert.equal(await placeDefinition(fits, TYPES), fits);
});

test('a never-placed definition is laid out whole', async () => {
  const def = seed('levy_case');
  def.nodes = def.nodes.map((n) => ({ ...n, position: { x: 0, y: 0 } }));
  const placed = await placeDefinition(def, TYPES);
  assert.deepEqual(crowded(rects(placed)), []);
});

test('the baked seeds are current', async () => {
  for (const def of SEEDS) {
    const laid = applyLayout(def, await layoutDefinition(def, TYPES));
    assert.deepEqual(
      laid.nodes.map((n) => [n.id, n.position]),
      def.nodes.map((n) => [n.id, n.position]),
      `${def.id} is stale: run pnpm --filter @ops-ai/console bake:workflows`,
    );
  }
});

test('an unknown type and an undrawn port still lay out', async () => {
  const def = seed('mail_intake');
  def.nodes.push({ id: 'mystery', type: 'ops.gone', typeVersion: 9, name: 'Gone' });
  def.connections.push({ from: { node: def.nodes[1].id, port: 'nope' }, to: { node: 'mystery', port: 'in' } });
  const laid = await layoutDefinition(def, TYPES);
  assert.equal(Object.keys(laid.positions).length, def.nodes.length);
  assert.deepEqual(crowded(rects(def, laid.positions)), []);
});

test('rowFallback places every step apart', () => {
  const def = seed('levy_case');
  assert.deepEqual(crowded(rects(def, rowFallback(definitionGraph(def, TYPES)).positions)), []);
});

test('a 50-step workflow lays out in 200 ms or less', async () => {
  const def = fiftySteps();
  assert.equal(def.nodes.length, 50);
  await layoutDefinition(def, TYPES);
  const runs: number[] = [];
  for (let i = 0; i < 5; i++) {
    const t = performance.now();
    await layoutDefinition(def, TYPES);
    runs.push(performance.now() - t);
  }
  const median = runs.sort((a, b) => a - b)[2];
  console.log(`layout of 50 steps: median ${median.toFixed(1)} ms over 5 runs`);
  assert.ok(median <= 200, `median ${median} ms`);
});
