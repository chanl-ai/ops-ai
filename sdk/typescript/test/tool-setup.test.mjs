// Setting an agent up end to end, by failure mode against a fake fetch: an import that brings in more or fewer
// operations than were ticked; a security decision sent for a version that waits on none; a grant that drops the tools
// the agent already holds; and a held write approved without the step-up it asks for.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { BadRequest, OpsAI } from '../dist/index.js';

const SPEC = { operations: [{ name: 'get_account' }, { name: 'get_statement' }, { name: 'place_hold' }] };

function client(answer, seen = []) {
  return new OpsAI({
    apiKey: 'ok_test', baseUrl: 'https://ops.test', team: 'team_a',
    fetch: async (url, init = {}) => {
      const u = new URL(url);
      const body = init.body ? JSON.parse(init.body) : undefined;
      seen.push({ path: u.pathname, method: init.method ?? 'GET', body });
      const [status, data] = answer({ path: u.pathname, body });
      return new Response(JSON.stringify(status >= 400 ? { success: false, error: data } : { success: true, data }), { status });
    },
  });
}

test('import brings in exactly the ticked operations and refuses a name the document lacks', async () => {
  const seen = [];
  const ops = client(({ path }) => [200, path.endsWith('/discover') ? SPEC : { id: 'mod_1' }], seen);
  await ops.tools.importOpenapi('mod_1', 'https://api.bank.test/openapi.json', ['get_account', 'place_hold']);
  const sent = seen.at(-1).body;
  assert.deepEqual(sent.operations.map((o) => o.name), ['get_account', 'place_hold']);
  assert.deepEqual(sent.source, { kind: 'openapi', specUrl: 'https://api.bank.test/openapi.json' });
  await assert.rejects(ops.tools.importOpenapi('mod_1', 'https://api.bank.test/openapi.json', ['place_holds']), /place_holds/);
});

test('a review decision goes to the review the version waits on', async () => {
  const seen = [];
  const waiting = { id: 'mod_1', versions: [{ status: 'published' }, { status: 'in_review', reviewId: 'rev_9' }] };
  const ops = client(() => [200, waiting], seen);
  await ops.tools.decideReview('mod_1', 'approved', { reason: 'reads only' });
  const decision = seen.find((r) => r.method === 'POST');
  assert.ok(decision.path.endsWith('/v1/publish-requests/rev_9/decision'));
  assert.deepEqual(decision.body, { decision: 'approved', reason: 'reads only' });
  const quiet = client(() => [200, { id: 'mod_1', versions: [{ status: 'published' }] }]);
  await assert.rejects(quiet.tools.decideReview('mod_1'), /request one first/);
});

test('granting tools keeps the ones the agent already holds', async () => {
  const seen = [];
  const ops = client(() => [200, { id: 'agt_1', toolIds: ['op:a', 'op:b'] }], seen);
  await ops.agents.grantTools('agt_1', ['op:b', 'op:c']);
  assert.deepEqual(seen.at(-1).body, { toolIds: ['op:a', 'op:b', 'op:c'] });
});

test('a held write asks for the step-up and is retried once with its token', async () => {
  const seen = [];
  const ops = client(({ path, body }) => {
    if (path.endsWith('/step-up')) return [200, { token: 'su_1' }];
    if (body?.stepUpToken) return [200, { decided: 'approve' }];
    return [400, { code: 'step_up_required', message: 'confirm it is you' }];
  }, seen);
  assert.deepEqual(await ops.tasks.approve('thr_1', { password: 'pw' }), { decided: 'approve' });
  assert.equal(seen.at(-1).body.stepUpToken, 'su_1');
  await assert.rejects(ops.tasks.approve('thr_1'), BadRequest);
});
