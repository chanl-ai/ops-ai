import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { APP_STATES, appStateFor, type AppStateId } from './app-state.ts';

// The states tools-service can answer, read from its OpenAPI document, so a new state cannot ship without words and
// an action here.
const openapi = JSON.parse(readFileSync(new URL('../../../../services/tools-service/openapi.json', import.meta.url), 'utf8'));
const answered: string[] = openapi.components.schemas.SystemCard.properties.appState.enum;

test('every app state the API answers has a label and an action for an admin and a member', () => {
  assert.ok(answered.length >= 7, `read ${answered.length} states`);
  for (const s of answered) {
    const shown = APP_STATES[s as AppStateId];
    assert.ok(shown, `no entry for ${s}`);
    assert.ok(shown.label && shown.admin && shown.member && shown.group, `${s} lacks a label, an action or a group`);
  }
  assert.deepEqual(Object.keys(APP_STATES).sort(), [...answered].sort());
});

test('an app off with no auth config sends an admin to add one and a member to ask', () => {
  assert.equal(appStateFor('needs_auth_config', true).action, 'add_auth_config');
  assert.equal(appStateFor('needs_auth_config', false).action, 'ask_admin');
  assert.equal(appStateFor('off', true).action, 'turn_on');
});
