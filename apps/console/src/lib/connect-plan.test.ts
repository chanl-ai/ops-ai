import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  complete,
  draftFor,
  environmentBody,
  fieldsFor,
  initialState,
  isRequired,
  leading,
  ordered,
  planFor,
  pluginGroups,
  reduce,
  turnOnBody,
  type Kind,
  type Kinds,
  type PluginSpec,
} from './connect-plan.ts';

const field = (name: string, extra: Partial<Kind['fields'][number]> = {}) => ({ name, label: name, secret: false, required: false, advanced: false, ...extra });
const kind = (id: string, extra: Partial<Kind> = {}): Kind => ({ id, label: id, fields: [], signsIn: false, holdsToken: false, perPerson: false, ...extra });
const KINDS: Kinds = {
  kinds: [],
  environments: [
    { id: 'test', label: 'Test', production: false },
    { id: 'production', label: 'Production', production: true },
  ],
  common: [field('baseUrl', { required: true }), field('testPath', { default: '/health' })],
  certificate: [field('clientCertificate', { secret: true })],
};

test('a kind tools-service adds later gets its form from its flags and fields, with no change to the dialog', () => {
  const jwt = kind('oauth2_jwt_bearer', {
    holdsToken: true,
    fields: [field('issuer', { required: true }), field('privateKey', { secret: true, required: true })],
  });
  const plan = planFor(jwt);
  assert.equal(plan.kind, 'keys');
  const groups = fieldsFor(jwt, KINDS);
  assert.deepEqual(
    groups.main.map((f) => f.name),
    ['baseUrl', 'testPath', 'issuer', 'privateKey'],
  );
  assert.deepEqual(
    groups.more.map((f) => f.name),
    ['clientCertificate'],
  );
  assert.equal(planFor(kind('device_code', { signsIn: true })).kind, 'account');
  assert.equal(planFor(kind('none')).kind, 'none');
});

test('in edit, a sealed secret reads as set, counts as filled, and a blank one is never sent so it keeps its value', () => {
  const k = kind('api_key', { fields: [field('apiKey', { secret: true, required: true }), field('header', { default: 'X-Api-Key' })] });
  const groups = fieldsFor(k, KINDS);
  const draft = draftFor('production', groups, { set: true, settings: { baseUrl: 'https://api.bank.test', header: '' }, secrets: { apiKey: { set: true } } });
  assert.equal(draft.secretSet.apiKey, true);
  assert.equal(draft.settings.header, 'X-Api-Key', 'a blank saved value falls back to the default');
  assert.equal(complete(draft, groups), true);
  assert.deepEqual(environmentBody(draft, 4).secretValues, {});
  const cleared = reduce(
    reduce(initialState({ test: draft, production: draft }, 'c1'), { type: 'secret', environment: 'production', name: 'apiKey', value: 'x' }),
    { type: 'secret', environment: 'production', name: 'apiKey', value: '' },
  );
  assert.deepEqual(environmentBody(cleared.sections.production, 4).secretValues, {}, 'typed then cleared would unseal the key');
  const typed = reduce(initialState({ test: draftFor('test', groups), production: draft }, 'c1'), {
    type: 'secret',
    environment: 'production',
    name: 'apiKey',
    value: 'new-key',
  });
  assert.deepEqual(environmentBody(typed.sections.production, 4), {
    revision: 4,
    settings: { baseUrl: 'https://api.bank.test', header: 'X-Api-Key', testPath: '/health' },
    secretValues: { apiKey: 'new-key' },
  });
});

test('a second save or test while one is under way is ignored, and a refused one frees the dialog', () => {
  const groups = fieldsFor(kind('bearer'), KINDS);
  let s = initialState({ test: draftFor('test', groups), production: draftFor('production', groups) }, 'c1');
  s = reduce(s, { type: 'start', environment: 'test', status: 'testing' });
  const again = reduce(s, { type: 'start', environment: 'production', status: 'saving' });
  assert.equal(again, s);
  assert.equal(again.sections.production.status, 'empty');
  s = reduce(s, { type: 'saved', environment: 'test', secretSet: { token: true } });
  assert.equal(s.busy, true, 'the save inside a test frees the dialog before the test answers');
  assert.equal(s.sections.test.status, 'testing');
  s = reduce(s, { type: 'failed', environment: 'test', message: 'refused' });
  assert.equal(s.busy, false);
  assert.equal(s.error, 'refused');
  s = reduce(s, { type: 'start', environment: 'production', status: 'testing' });
  s = reduce(s, { type: 'tested', environment: 'production', health: { status: 'failed', httpStatus: 401, at: 'now' } });
  assert.equal(s.sections.production.status, 'failed');
});

test('environments are the service list: a team-named one gets a section, and the one marked production leads', () => {
  const team: Kinds = {
    ...KINDS,
    environments: [
      { id: 'mock', label: 'Mock', production: false },
      { id: 'uat', label: 'UAT', production: false },
      { id: 'live', label: 'Live', production: true },
    ],
  };
  assert.deepEqual(
    ordered(team).map((e) => e.label),
    ['Mock', 'UAT', 'Live'],
  );
  assert.deepEqual(
    ordered(team, 'live').map((e) => e.id),
    ['live', 'mock', 'uat'],
  );
  assert.equal(leading(team, ['uat', 'live']), 'live');
  assert.equal(leading(team, ['uat', 'mock']), 'mock');
});

test('a field required only for some settings follows them: a signed client needs its key and not its secret', () => {
  const clientAuth = field('clientAuth', { choices: ['body', 'basic', 'private_key_jwt'], default: 'body' });
  const secret = field('clientSecret', { secret: true, required: true, optionalWhen: { clientAuth: 'private_key_jwt' } });
  const key = field('signingKey', { secret: true, requiredWhen: { clientAuth: 'private_key_jwt' } });
  const k = kind('oauth2_client_credentials', { fields: [clientAuth, secret, key] });
  const groups = fieldsFor(k, KINDS);
  assert.equal(isRequired(secret, { clientAuth: 'body' }), true);
  assert.equal(isRequired(key, { clientAuth: 'body' }), false);
  let s = initialState({ test: draftFor('test', groups) }, 'c1');
  s = reduce(s, { type: 'setting', environment: 'test', name: 'baseUrl', value: 'https://idp.example' });
  s = reduce(s, { type: 'setting', environment: 'test', name: 'clientAuth', value: 'private_key_jwt' });
  assert.equal(complete(s.sections.test, groups), false, 'a signed client with no key counts as filled');
  s = reduce(s, { type: 'secret', environment: 'test', name: 'signingKey', value: 'a signing key' });
  assert.equal(complete(s.sections.test, groups), true, 'the secret it no longer needs still blocks it');
});

test('a plugin that fixes how its key is sent never asks for it, so the key goes out under the plugin header only', () => {
  const apiKey = kind('api_key', {
    fields: [
      field('placement', { advanced: true, default: 'header' }),
      field('name', { required: true, default: 'X-Api-Key' }),
      field('key', { secret: true, required: true }),
    ],
  });
  const plugin: PluginSpec = {
    settings: [{ name: 'base_url', label: 'System address', default: 'https://api.multi.test', secret: false, perEnvironment: false, locked: false }],
    fixed: ['name', 'placement'],
  };
  const groups = pluginGroups(apiKey, KINDS, plugin, 'own');
  assert.deepEqual(
    [...groups.main, ...groups.more].map((f) => f.name),
    ['key', 'clientCertificate'],
  );
  let s = initialState({ test: draftFor('test', groups) }, null);
  s = reduce(s, { type: 'secret', environment: 'test', name: 'key', value: 'desk-key-1' });
  const body = turnOnBody(apiKey, plugin, 'own', s.sections.test, { base_url: 'https://api.multi.test' }, true);
  assert.deepEqual(body, {
    enabled: true,
    environment: 'test',
    settings: { base_url: 'https://api.multi.test' },
    kind: 'api_key',
    credentials: { key: 'desk-key-1' },
  });
});

test('a plugin that signs in sends the team app only when its own is chosen, and a sandbox address as that environment setting', () => {
  const oauth = kind('oauth2_auth_code', { signsIn: true, fields: [field('clientId', { required: true }), field('clientSecret', { secret: true })] });
  const plugin: PluginSpec = {
    settings: [{ name: 'login_url', label: 'Sign-in address', default: null, secret: false, perEnvironment: true, locked: false }],
    fixed: [],
  };
  const own = pluginGroups(oauth, KINDS, plugin, 'own');
  assert.deepEqual(
    own.main.map((f) => f.name),
    ['clientId', 'clientSecret', 'login_url'],
  );
  assert.deepEqual(
    pluginGroups(oauth, KINDS, plugin, 'platform').main.map((f) => f.name),
    ['login_url'],
  );
  let s = initialState({ test: draftFor('test', own) }, 'con_1');
  s = reduce(s, { type: 'setting', environment: 'test', name: 'clientId', value: 'uat-app' });
  s = reduce(s, { type: 'setting', environment: 'test', name: 'login_url', value: 'https://test.login.example' });
  assert.deepEqual(turnOnBody(oauth, plugin, 'own', s.sections.test, {}, false), {
    enabled: true,
    environment: 'test',
    settings: { login_url: 'https://test.login.example' },
    clientId: 'uat-app',
  });
  const platform = turnOnBody(oauth, plugin, 'platform', s.sections.test, {}, false);
  assert.equal('clientId' in platform, false, 'the platform app was chosen, yet the team client ID went out');
});
