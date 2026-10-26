// The hand-written layer, by failure mode, against a fake fetch: a call that loses the key or team, a caller who sees
// the envelope, a refusal that loses its code or request id, a list that stops after one page, a write retried without
// an idempotency key, and a wait that hangs on a run stopped at a human task.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Conflict, NotFound, OpsAI } from '../dist/index.js';

const ok = (data) => new Response(JSON.stringify({ success: true, data }), { status: 200 });
const client = (handler, extra = {}) =>
  new OpsAI({ apiKey: 'ok_test', baseUrl: 'https://ops.test', team: 'team_a', fetch: async (url, init) => handler(new URL(url), init ?? {}), ...extra });

test('every call carries the key and team and returns the data', async () => {
  let seen;
  const agent = await client((url, init) => { seen = { url, init }; return ok({ id: 'ag_1' }); }).agents.get('ag_1');
  assert.deepEqual(agent, { id: 'ag_1' });
  assert.equal(seen.url.href, 'https://ops.test/api/agents/v1/agents/ag_1');
  assert.equal(seen.init.headers['X-Api-Key'], 'ok_test');
  assert.equal(seen.init.headers['X-Team-Id'], 'team_a');
});

test('a refusal throws its class with the code and request id', async () => {
  const body = { success: false, error: { code: 'not_found', message: 'No such agent', requestId: 'req_9' } };
  await assert.rejects(
    client(() => new Response(JSON.stringify(body), { status: 404 })).agents.get('ag_x'),
    (e) => e instanceof NotFound && e.code === 'not_found' && e.requestId === 'req_9',
  );
});

test('a list walks every page', async () => {
  const c = client((url) => {
    const page = Number(url.searchParams.get('page') ?? 1);
    return ok({ items: [`a${page}`], pagination: { page, hasNext: page < 3 } });
  });
  const seen = [];
  for await (const a of c.agents.list()) seen.push(a);
  assert.deepEqual(seen, ['a1', 'a2', 'a3']);
});

test('a read is retried and a write without a key is not', async () => {
  const calls = { GET: 0, POST: 0 };
  const c = client((_, init) => {
    calls[init.method] += 1;
    return calls[init.method] === 1 ? new Response('{}', { status: 503 }) : ok({ id: 'x' });
  }, { maxRetries: 1 });
  assert.deepEqual(await c.agents.get('ag_1'), { id: 'x' });
  await assert.rejects(c.agents.create({ name: 'x' }));
  assert.deepEqual(calls, { GET: 2, POST: 1 });
});

test('wait returns at a human task with its id, and decide then finishes the run', async () => {
  let status = 'waiting';
  const c = client((url, init) => {
    if (init.method === 'POST' && url.pathname.endsWith('/decision')) {
      assert.deepEqual(JSON.parse(init.body), { decision: 'approve' });
      status = 'succeeded';
      return ok({ id: 'rv_1' });
    }
    if (init.method === 'POST') return new Response(JSON.stringify({ success: false, error: { code: 'already_decided', message: 'x' } }), { status: 409 });
    return ok({ id: 'run_1', status, waiting: status === 'waiting' ? { node: 'review', iteration: 0, payload: { review_id: 'rv_1' } } : null });
  });
  const run = await c.runs.wait('run_1', { intervalMs: 0 });
  assert.equal(run.taskId, 'rv_1');
  await c.tasks.decide(run.taskId, 'approve');
  assert.equal((await c.runs.wait('run_1', { intervalMs: 0 })).status, 'succeeded');
  await assert.rejects(c.raw.agents.reviews_bulk_decide({ body: { ids: [], decision: 'approve' } }), Conflict);
});
