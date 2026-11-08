// The Apps area in the screen's words, by failure mode against a fake fetch: Connected lists an app whose
// account never signed in; a tool run goes to another module of the app, or Mock reaches the system; the team's own
// client is saved without the revision the route needs; a caller gets the envelope instead of Usage's rows; turning on
// a custom app sends a request to a plugin route; and a document type's copy is made in agents-service.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { OpsAI } from '../dist/index.js';

const PAGE = { card: { id: 'con_desk', kind: 'custom', moduleIds: ['mod_a', 'mod_b'] }, connection: { id: 'con_desk' } };

function client(answers, seen = []) {
  return new OpsAI({
    apiKey: 'ok_test', baseUrl: 'https://ops.test', team: 'team_a',
    fetch: async (url, init = {}) => {
      const u = new URL(url);
      seen.push({ url: u, method: init.method ?? 'GET', body: init.body ? JSON.parse(init.body) : undefined });
      const data = answers[`${init.method ?? 'GET'} ${decodeURIComponent(u.pathname).split('/v1/')[1]}`] ?? {};
      return new Response(JSON.stringify({ success: true, data }), { status: 200 });
    },
  });
}

test('connected keeps signed-in and built-in apps only', async () => {
  const cards = [
    { id: 'plugin:desk', kind: 'plugin', state: 'connected', status: 'healthy' },
    { id: 'plugin:crm', kind: 'plugin', state: 'not_signed_in', status: 'healthy' },
    { id: 'builtin:files', kind: 'builtin', status: 'available' },
  ];
  const ops = client({ 'GET apps': cards });
  assert.deepEqual((await ops.apps.list({ connected: true })).map((c) => c.id), ['plugin:desk', 'builtin:files']);
});

test('a tool runs on the module that holds it and Mock says mock', async () => {
  const seen = [];
  const ops = client({
    'GET apps/con_desk': PAGE,
    'GET tool-modules/mod_a': { id: 'mod_a', operations: [{ name: 'write_record' }] },
    'GET tool-modules/mod_b': { id: 'mod_b', operations: [{ name: 'read_record' }] },
  }, seen);
  await ops.tools.run('con_desk', 'read_record', { id: 'r1' });
  const run = seen.at(-1);
  assert.equal(run.url.pathname, '/api/tools/v1/tool-modules/mod_b/operations/read_record/run');
  // Left to the gateway, a run is a test run: the app's sandbox account when it has one.
  assert.deepEqual(run.body, { mode: 'mock', input: { id: 'r1' } });
});

test("an account picks the team's credential by its id with its revision", async () => {
  const seen = [];
  const ops = client({ 'GET apps/plugin:desk': { ...PAGE, connection: { id: 'con_team' } }, 'GET apps/plugin:desk/accounts/con_team': { revision: 4 } }, seen);
  await ops.credentials.set('plugin:desk', 'cred_bank');
  const put = seen.at(-1);
  assert.equal(put.method, 'PATCH');
  assert.equal(decodeURIComponent(put.url.pathname), '/api/tools/v1/apps/plugin:desk/accounts/con_team');
  assert.deepEqual(put.body, { revision: 4, credentialId: 'cred_bank' });
});

test("usage is the calls' rows, not the envelope", async () => {
  const rows = [{ id: 'gwc_1' }];
  assert.deepEqual(await client({ 'GET executions': { data: rows, pagination: { page: 1 } } }).usage.list(), rows);
});

test('a custom app is not turned on through a plugin route', async () => {
  const seen = [];
  assert.throws(() => client({}, seen).apps.turnOn('con_desk'), /not an app a plugin brings/);
  assert.equal(seen.length, 0);
});

test("a document type's copy is made in documents-service", async () => {
  const seen = [];
  await client({}, seen).resources.add({ source: 'plugin:desk', id: 'case-letter', kind: 'document_type' });
  assert.equal(decodeURIComponent(seen.at(-1).url.pathname), '/api/documents/v1/resources/plugin:desk:case-letter/copies');
});

test('credentials.list answers the rows of the app credentials route', async () => {
  const seen = [];
  const rows = [{ id: 'con_desk', app: 'plugin:desk', type: 'own', accounts: 2, status: 'working' }];
  const ops = client({ 'GET app-credentials': rows }, seen);
  assert.deepEqual(await ops.credentials.list(), rows);
  assert.ok(seen.at(-1).url.pathname.endsWith('/v1/app-credentials'));
});

test('credentials.create posts the app, its client and secret to the app credentials route', async () => {
  const seen = [];
  const row = { id: 'con_desk', app: 'plugin:desk', type: 'own' };
  const ops = client({ 'POST app-credentials': row }, seen);
  assert.deepEqual(await ops.credentials.create('plugin:desk', { clientId: 'bank-app', clientSecret: 's3' }), row);
  assert.equal(seen.at(-1).method, 'POST');
  assert.deepEqual(seen.at(-1).body, { app: 'plugin:desk', clientId: 'bank-app', clientSecret: 's3' });
});

test('a sandbox account is added as a sandbox under its app', async () => {
  const seen = [];
  await client({}, seen).accounts.add('plugin:desk', 'Desk sandbox', { sandbox: true, credentialId: 'cred_uat' });
  const made = seen.at(-1);
  assert.equal(made.method, 'POST');
  assert.equal(decodeURIComponent(made.url.pathname), '/api/tools/v1/apps/plugin:desk/accounts');
  assert.deepEqual(made.body, { name: 'Desk sandbox', sandbox: true, credentialId: 'cred_uat' });
});

test("a copy is removed by the delete of the service that keeps its kind", async () => {
  const seen = [];
  const ops = client({}, seen);
  const made = { copy: { kind: 'document_type', recordId: 'dt_1', source: 'plugin:desk', templateId: 'case-letter' } };
  await ops.resources.remove(made);
  assert.deepEqual([seen.at(-1).method, seen.at(-1).url.pathname], ['DELETE', '/api/documents/v1/document-types/dt_1']);
  await ops.resources.remove({ ...made.copy, kind: 'workflow', recordId: 'case_review_1' });
  assert.deepEqual([seen.at(-1).method, seen.at(-1).url.pathname], ['DELETE', '/api/agents/v1/workflows/definitions/case_review_1']);
});

test("the resources list is the app's one list, and an update names the copy", async () => {
  const seen = [];
  const ops = client({}, seen);
  await ops.resources.list('plugin:desk');
  assert.equal(decodeURIComponent(seen.at(-1).url.pathname), '/api/tools/v1/apps/plugin:desk/resources');
  await ops.resources.update({ copy: { kind: 'agent', recordId: 'ag_1', source: 'plugin:desk', templateId: 'case-helper' } }, { confirm: true });
  assert.equal(decodeURIComponent(seen.at(-1).url.pathname), '/api/agents/v1/resources/plugin:desk:case-helper/copies/ag_1/update');
});

test('a connector is disconnected on its primary account, not the app\'s first', async () => {
  const rows = [{ appId: 'plugin:github', name: 'GitHub', primaryAccountId: 'con_second', accountCount: 2 }];
  const seen = [];
  const ops = client({ 'GET me/connections': rows }, seen);
  assert.deepEqual(await ops.me.connectors.list(), rows);
  await ops.me.connectors.disconnect('github');
  assert.equal(seen.at(-1).method, 'DELETE');
  assert.equal(seen.at(-1).url.pathname, '/api/tools/v1/me/accounts/con_second');
  await assert.rejects(ops.me.connectors.disconnect('plugin:hubspot'), /not one of your connectors/);
});
