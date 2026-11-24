// The schedule noun by failure mode: a rule's fields sent outside `rule` or without their kind, a verb calling the
// wrong path or method, and a clear that expects a body from a 204.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { OpsAI } from '../dist/index.js';

const STEP = '/v1/workflows/definitions/held_wires/triggers/start/schedule';
const RULE = { kind: 'every', every: 15, unit: 'minutes', start: '07:00', tz: 'Europe/London' };

const client = (seen, status = 200, data = {}) =>
  new OpsAI({
    apiKey: 'ok',
    baseUrl: 'https://ops.test',
    team: 't',
    fetch: async (url, init) => {
      seen.push({ url: new URL(url), method: init?.method ?? 'GET', body: init?.body ? JSON.parse(init.body) : undefined });
      return status === 204 ? new Response(null, { status }) : new Response(JSON.stringify({ success: true, data }), { status });
    },
  });

test('save and preview send the kind and its own fields inside rule', async () => {
  const seen = [];
  const c = client(seen);
  await c.workflows.schedules.save('held_wires', 'start', RULE);
  await c.workflows.schedules.preview(RULE);
  assert.deepEqual(seen.map((r) => [r.method, r.url.pathname.replace('/api/agents', ''), r.body]), [
    ['PUT', STEP, { rule: RULE }],
    ['POST', '/v1/schedules/preview', { rule: RULE }],
  ]);
});

test('show, clear and kinds use their own paths', async () => {
  const seen = [];
  const c = client(seen, 200, []);
  await c.workflows.schedules.kinds();
  await c.workflows.schedules.show('held_wires', 'start');
  await client(seen, 204).workflows.schedules.clear('held_wires', 'start');
  assert.deepEqual(seen.map((r) => [r.method, r.url.pathname.replace('/api/agents', '')]), [
    ['GET', '/v1/schedules/kinds'],
    ['GET', STEP],
    ['DELETE', STEP],
  ]);
});
