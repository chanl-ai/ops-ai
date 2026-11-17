// The agents lists by failure mode: a list that stops after its first page, a page size above the maximum, a batch
// body that carries a field the API refuses, and an inbox refused to a teammate.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { NotFound, OpsAI } from '../dist/index.js';

const client = (handler) =>
  new OpsAI({ apiKey: 'ok', baseUrl: 'https://ops.test', team: 't', fetch: async (url, init) => handler(new URL(url), init ?? {}) });

const threePages = (seen) => (url) => {
  seen.push(url);
  const page = Number(url.searchParams.get('page') ?? 1);
  return new Response(JSON.stringify({ success: true, data: { data: [`row${page}`], pagination: { page, hasNext: page < 3 } } }));
};

const lists = [
  ['/v1/agents', (c) => c.agents.list({ search: 'x' })],
  ['/v1/skills', (c) => c.skills.list({ ids: ['s1'] })],
  ['/v1/guardrails', (c) => c.guardrails.list({ search: 'x' })],
  ['/v1/widgets', (c) => c.widgets.list({ search: 'x' })],
  ['/v1/case-types', (c) => c.caseTypes.list({ search: 'x' })],
  ['/v1/task-types', (c) => c.taskTypes.list({ search: 'x' })],
  ['/v1/cases', (c) => c.cases.list({ ids: ['c1'] })],
  ['/v1/threads', (c) => c.threads.list({ graph: 'g' })],
  ['/v1/runs', (c) => c.runs.list({ workflowId: 'wf', status: ['failed'] })],
  ['/v1/workflows/definitions', (c) => c.workflows.list({ status: ['live'] })],
  ['/v1/workflows/wf/forms', (c) => c.workflows.forms('wf', { search: 'x' })],
];

for (const [path, call] of lists) {
  test(`${path} follows every page at the maximum size`, async () => {
    const seen = [];
    const rows = [];
    for await (const row of call(client(threePages(seen)))) rows.push(row);
    assert.deepEqual(rows, ['row1', 'row2', 'row3']);
    assert.deepEqual(seen.map((u) => u.pathname.replace('/api/agents', '')), [path, path, path]);
    assert.deepEqual([...new Set(seen.map((u) => u.searchParams.get('pageSize')))], ['50']);
  });
}

test('a batch start sends only the declared fields', async () => {
  const bodies = [];
  const c = client((_url, init) => {
    bodies.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ success: true, data: { batchId: 'b1' } }));
  });
  await c.workflows.startBatch('wf', 'file1', { mode: 'test', dryRun: true });
  await c.workflows.startBatch('wf', 'file1');
  assert.deepEqual(bodies, [{ fileId: 'file1', mode: 'test', dryRun: true }, { fileId: 'file1' }]);
});

test('an inbox refused to a teammate throws NotFound', async () => {
  const body = { success: false, error: { code: 'not_found', message: 'No such thread' } };
  await assert.rejects(client(() => new Response(JSON.stringify(body), { status: 404 })).threads.inbox('th1'), NotFound);
});

const cursorPages = (seen) => (url) => {
  seen.push(url);
  const n = Number(url.searchParams.get('cursor') ?? 0) + 1;
  return new Response(JSON.stringify({ success: true, data: { data: [`row${n}`], nextCursor: n < 3 ? String(n) : null } }));
};

test('toolOptions follows nextCursor and never asks above the maximum', async () => {
  const seen = [];
  assert.deepEqual(await client(cursorPages(seen)).agents.toolOptions('x'), ['row1', 'row2', 'row3']);
  assert.deepEqual(seen.map((u) => u.searchParams.get('cursor')), [null, '1', '2']);
  assert.deepEqual([...new Set(seen.map((u) => u.searchParams.get('limit')))], ['50']);
});

test('everyThread follows every page at the maximum size', async () => {
  const seen = [];
  assert.deepEqual(await client(threePages(seen)).chat.everyThread({ test: true }), ['row1', 'row2', 'row3']);
  assert.deepEqual([...new Set(seen.map((u) => u.searchParams.get('pageSize')))], ['50']);
});
