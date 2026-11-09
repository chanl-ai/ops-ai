import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { APP_STATES, accountOwnerWords, appStateFor, headerActionFor, labelFor, whoseState, type AppGroupId, type AppStateId } from './app-state.ts';

// The states and groups tools-service can answer, read from its OpenAPI document, so a new one cannot ship without
// words and an action here.
const openapi = JSON.parse(readFileSync(new URL('../../../../services/tools-service/openapi.json', import.meta.url), 'utf8'));
const card = openapi.components.schemas.SystemCard.properties;
const answered: string[] = card.appState.enum;
const groups: string[] = card.appGroup.enum;

test('every app state the API answers has a label and an action for an admin and a member', () => {
  assert.ok(answered.length >= 8, `read ${answered.length} states`);
  for (const s of answered) {
    const shown = APP_STATES[s as AppStateId];
    assert.ok(shown, `no entry for ${s}`);
    assert.ok(shown.label && shown.admin && shown.member, `${s} lacks a label or an action`);
  }
  assert.deepEqual(Object.keys(APP_STATES).sort(), [...answered].sort());
  const known: AppGroupId[] = ['on', 'needs_you', 'needs_admin', 'gone'];
  assert.deepEqual([...groups].sort(), [...known].sort());
});

test('an app off with no auth config sends an admin to add one and a member to ask', () => {
  assert.equal(appStateFor('needs_auth_config', 'needs_admin', true).action, 'add_auth_config');
  assert.equal(appStateFor('needs_auth_config', 'needs_admin', false).action, 'ask_admin');
  assert.equal(appStateFor('off', 'needs_admin', true).action, 'turn_on');
});

test('a sign-in the team account needs is asked of an admin; one that is the person’s own is theirs', () => {
  assert.equal(appStateFor('needs_sign_in', 'needs_admin', false).action, 'ask_admin');
  assert.equal(appStateFor('needs_sign_in', 'needs_you', false).action, 'sign_in');
  assert.equal(appStateFor('auth_config_broken', 'needs_admin', true).action, 'fix_auth_config');
  assert.equal(APP_STATES.auth_config_broken.on, true);
});

test('the app page header: a member on a connected team app has nothing to do; an admin may connect another account', () => {
  assert.equal(headerActionFor({ appState: 'connected', appGroup: 'on', mayManage: false }), null);
  assert.equal(headerActionFor({ appState: 'connected', appGroup: 'on', mayManage: true }), 'connect');
  // A member whose team account needs signing in asks an admin; one whose own sign-in is missing goes to Mine.
  assert.equal(headerActionFor({ appState: 'needs_sign_in', appGroup: 'needs_admin', mayManage: false }), 'ask_admin');
  assert.equal(headerActionFor({ appState: 'needs_sign_in', appGroup: 'needs_you', mayManage: false }), 'own_sign_in');
  assert.equal(headerActionFor({ appState: 'auth_config_broken', appGroup: 'needs_admin', mayManage: true }), 'fix_auth_config');
  assert.equal(headerActionFor({ appState: 'removed', appGroup: 'gone', mayManage: true }), null);
});

test('someone who cannot set an app up reads one line: it is not set up for their team, and to ask', () => {
  for (const state of ['needs_auth_config', 'off'] as const) {
    assert.equal(labelFor(state, false), 'Not set up for your team yet');
    assert.equal(appStateFor(state, 'needs_admin', false).action, 'ask_admin');
  }
  assert.equal(labelFor('needs_auth_config', true), 'Needs an auth config');
  assert.equal(labelFor('connected', false), 'Connected');
});

test('on an app each person signs in to, the badge is the person’s own and the team’s account row says it is the team’s', () => {
  assert.equal(whoseState({ ownSignIn: 'none', appGroup: 'needs_you' }), 'You');
  assert.equal(whoseState({ ownSignIn: null, appGroup: 'on' }), null);
  assert.equal(whoseState({ ownSignIn: 'connected', appGroup: 'gone' }), null);
  assert.equal(accountOwnerWords('team'), 'Team account');
  assert.equal(accountOwnerWords('each'), null);
});
