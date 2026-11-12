import assert from 'node:assert/strict';
import { test } from 'node:test';

import { appPageHref } from './app-links.ts';

test('an app link reaches the app page route with its id encoded', () => {
  assert.equal(appPageHref('plugin:salesforce'), '/data/connectors/plugin%3Asalesforce');
  assert.equal(appPageHref('con_1', 'tools'), '/data/connectors/con_1?tab=tools');
});
