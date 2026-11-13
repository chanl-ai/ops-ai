import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  accountBody,
  asksNothing,
  complete,
  draftFor,
  firstSignIn,
  fieldsFor,
  initialState,
  isRequired,
  newAccountBody,
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
  const draft = draftFor(groups, { settings: { baseUrl: 'https://api.bank.test', header: '' }, secrets: { apiKey: { set: true } } });
  assert.equal(draft.secretSet.apiKey, true);
  assert.equal(draft.settings.header, 'X-Api-Key', 'a blank saved value falls back to the default');
  assert.equal(complete(draft, groups), true);
  assert.deepEqual(accountBody(draft, 4).secretValues, {});
  const cleared = reduce(reduce(initialState(draft, 'c1', true), { type: 'secret', name: 'apiKey', value: 'x' }), { type: 'secret', name: 'apiKey', value: '' });
  assert.deepEqual(accountBody(cleared.draft, 4).secretValues, {}, 'typed then cleared would unseal the key');
  const typed = reduce(initialState(draft, 'c1', true), { type: 'secret', name: 'apiKey', value: 'new-key' });
  assert.deepEqual(accountBody(typed.draft, 4), {
    revision: 4,
    settings: { baseUrl: 'https://api.bank.test', header: 'X-Api-Key', testPath: '/health' },
    secretValues: { apiKey: 'new-key' },
  });
});

test('a second save or test while one is under way is ignored, and a refused one frees the dialog', () => {
  const groups = fieldsFor(kind('bearer'), KINDS);
  let s = initialState(draftFor(groups), 'c1');
  s = reduce(s, { type: 'start', status: 'testing' });
  const again = reduce(s, { type: 'start', status: 'saving' });
  assert.equal(again, s);
  assert.equal(again.draft.status, 'testing');
  s = reduce(s, { type: 'saved', secretSet: { token: true } });
  assert.equal(s.busy, true, 'the save inside a test frees the dialog before the test answers');
  assert.equal(s.draft.status, 'testing');
  s = reduce(s, { type: 'failed', message: 'refused' });
  assert.equal(s.busy, false);
  assert.equal(s.error, 'refused');
  s = reduce(s, { type: 'start', status: 'testing' });
  s = reduce(s, { type: 'tested', health: { status: 'failed', httpStatus: 401, at: 'now' } });
  assert.equal(s.draft.status, 'failed');
});

test('a field required only for some settings follows them: a signed client needs its key and not its secret', () => {
  const clientAuth = field('clientAuth', { choices: ['body', 'basic', 'private_key_jwt'], default: 'body' });
  const secret = field('clientSecret', { secret: true, required: true, optionalWhen: { clientAuth: 'private_key_jwt' } });
  const key = field('signingKey', { secret: true, requiredWhen: { clientAuth: 'private_key_jwt' } });
  const k = kind('oauth2_client_credentials', { fields: [clientAuth, secret, key] });
  const groups = fieldsFor(k, KINDS);
  assert.equal(isRequired(secret, { clientAuth: 'body' }), true);
  assert.equal(isRequired(key, { clientAuth: 'body' }), false);
  let s = initialState(draftFor(groups), 'c1');
  s = reduce(s, { type: 'setting', name: 'baseUrl', value: 'https://idp.example' });
  s = reduce(s, { type: 'setting', name: 'clientAuth', value: 'private_key_jwt' });
  assert.equal(complete(s.draft, groups), false, 'a signed client with no key counts as filled');
  s = reduce(s, { type: 'secret', name: 'signingKey', value: 'a signing key' });
  assert.equal(complete(s.draft, groups), true, 'the secret it no longer needs still blocks it');
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
    settings: [{ name: 'base_url', label: 'System address', default: 'https://api.multi.test', secret: false, perAccount: false, locked: false }],
    fixed: ['name', 'placement'],
  };
  const groups = pluginGroups(apiKey, KINDS, plugin);
  assert.deepEqual(
    [...groups.main, ...groups.more].map((f) => f.name),
    ['key', 'clientCertificate'],
  );
  let s = initialState(draftFor(groups), null);
  s = reduce(s, { type: 'secret', name: 'key', value: 'desk-key-1' });
  const body = turnOnBody(apiKey, plugin, undefined, s.draft, { base_url: 'https://api.multi.test' }, true);
  assert.deepEqual(body, {
    enabled: true,
    sandbox: false,
    settings: { base_url: 'https://api.multi.test' },
    kind: 'api_key',
    credentials: { key: 'desk-key-1' },
  });
});

test('a plugin that signs in never asks for its client and names the picked app credential, and a sandbox its own sign-in address', () => {
  const oauth = kind('oauth2_auth_code', { signsIn: true, fields: [field('clientId', { required: true }), field('clientSecret', { secret: true })] });
  const plugin: PluginSpec = {
    settings: [{ name: 'login_url', label: 'Sign-in address', default: null, secret: false, perAccount: true, locked: false }],
    fixed: [],
  };
  const groups = pluginGroups(oauth, KINDS, plugin);
  assert.deepEqual(
    groups.main.map((f) => f.name),
    ['login_url'],
  );
  let s = initialState(draftFor(groups), 'con_1');
  s = reduce(s, { type: 'setting', name: 'login_url', value: 'https://test.login.example' });
  assert.deepEqual(newAccountBody(oauth, plugin, 'cred_uat', s.draft, 'Salesforce sandbox', true), {
    name: 'Salesforce sandbox',
    sandbox: true,
    kind: 'oauth2_auth_code',
    settings: { login_url: 'https://test.login.example' },
    credentialId: 'cred_uat',
  });
  assert.equal(turnOnBody(oauth, plugin, null, s.draft, {}, false).credentialId, null, 'Ops AI’s app is named as no credential');
  const kept = turnOnBody(oauth, plugin, undefined, s.draft, {}, false);
  assert.equal('credentialId' in kept, false, 'a later turn-on that picks nothing would change the account’s app');
  assert.equal('clientId' in kept || 'clientSecret' in kept, false, 'a client was typed into a turn-on');
});

test('an account signed in through the dialog is remembered, so Save opens no second sign-in for it', () => {
  let s = initialState(draftFor({ main: [], more: [] }), 'con_1', true);
  assert.equal(s.signedIn, false);
  s = reduce(reduce(s, { type: 'signing-in' }), { type: 'signed-in' });
  assert.equal(s.signedIn, true);
});

// The Turn on window sends its choice, so its preselection is the default a first turn-on gets: the team's account
// wherever the app offers it, else the first way the app signs in.
test('the Turn on window preselects the team account where the app offers it', () => {
  assert.equal(firstSignIn(['team', 'person', 'person_or_team']), 'team');
  assert.equal(firstSignIn(['person_or_team', 'person']), 'person_or_team');
});

test('a plugin with no sign-in and nothing to set turns on without a form; one with a key or a setting asks', () => {
  const settings = (names: string[], locked = false) => names.map((name) => ({ name, label: name, secret: false, perAccount: false, locked }));
  assert.equal(asksNothing({ kinds: ['none'], settings: [] }), true);
  assert.equal(asksNothing({ kinds: ['none'], settings: settings(['api_version'], true) }), true);
  assert.equal(asksNothing({ kinds: ['none'], settings: settings(['site_url']) }), false);
  assert.equal(asksNothing({ kinds: ['basic', 'bearer'], settings: [] }), false);
  assert.equal(asksNothing({ kinds: ['oauth2_auth_code'], settings: [] }), false);
});
