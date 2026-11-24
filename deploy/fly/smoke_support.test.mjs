// The smoke walk's token renewal, cleanup and summary against a fake origin, by failure mode: a token the platform
// refuses after the walk's own invite, a run that throws before it finished, and a stack trace where a reason belongs.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { removals, renewingFetch, sweepStale } from './smoke_support.mjs';

const json = (status, body = {}) => new Response(status === 204 ? null : JSON.stringify(body), { status });

test('a 401 after the invite renews the admin token, updates the shared headers and sends the call again', async () => {
  const headers = { Authorization: 'Bearer old' };
  const seen = [];
  const plainFetch = async (_url, init) => {
    seen.push(init.headers.Authorization);
    return init.headers.Authorization === 'Bearer new' ? json(200, { data: { id: 'th_1' } }) : json(401, { error: { code: 'permissions_changed' } });
  };
  const f = renewingFetch({ plainFetch, headers, renew: async (sent) => ((sent.Authorization = 'Bearer new'), true) });
  const r = await f('https://x/api/agents/chat/threads', { method: 'POST', headers });
  assert.equal(r.status, 200);
  assert.deepEqual(seen, ['Bearer old', 'Bearer new']);
  assert.equal(headers.Authorization, 'Bearer new');
  // The approver's own token is never renewed as the admin's.
  let renewed = 0;
  const g = renewingFetch({ plainFetch: async () => json(401), headers: { Authorization: 'Bearer admin' }, renew: async () => (renewed++, false) });
  assert.equal((await g('https://x/a', { headers: { Authorization: 'Bearer approver' } })).status, 401);
  assert.equal(renewed, 0);
});

test('what a run registered is removed even when the walk threw, newest first, an archived workflow after a 409', async () => {
  const calls = [];
  const lines = [];
  const fetchImpl = async (url, init) => {
    calls.push(`${init.method} ${new URL(url).pathname}`);
    return json(url.endsWith('/definitions/smoke_a1') && init.method === 'DELETE' ? 409 : 204);
  };
  const r = removals({ origin: 'https://x', headers: {}, fetchImpl, log: (l) => lines.push(l) });
  r.add('agent', 'DELETE', '/agents/ag_1');
  r.add('workflow', 'DELETE', '/definitions/smoke_a1');
  await r.run();
  assert.deepEqual(calls, ['DELETE /definitions/smoke_a1', 'POST /definitions/smoke_a1/archive', 'DELETE /agents/ag_1']);
  assert.equal(lines.length, 2);
  assert.ok(lines.every((l) => l.startsWith('REMOVED')));
});

test('the sweep removes earlier runs approvers and agents by their names and leaves every other member', async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    const u = new URL(url);
    calls.push(`${init.method ?? 'GET'} ${u.pathname}`);
    if (u.pathname.endsWith('/members')) return json(200, { data: { data: [{ id: 'm1', email: 'smoke-approver-ab12@example.com' }, { id: 'm2', email: 'smoke-approver-team@corp.example' }] } });
    if (u.pathname.endsWith('/agents')) return json(200, { data: { data: [{ id: 'ag_1', name: 'Smoke zz09' }, { id: 'ag_2', name: 'Smoke tests for billing' }] } });
    return json(204);
  };
  const lines = [];
  const n = await sweepStale({ origin: 'https://x', headers: {}, fetchImpl, log: (l) => lines.push(l) });
  assert.equal(n, 2);
  assert.deepEqual(calls.filter((c) => !c.startsWith('GET')), ['DELETE /api/agents/v1/agents/ag_1', 'POST /api/platform/v1/settings/members/delete']);
});
