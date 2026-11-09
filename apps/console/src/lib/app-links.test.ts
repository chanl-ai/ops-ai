import assert from 'node:assert/strict';
import { test } from 'node:test';

import { appPageHref } from './app-links.ts';

test('an app link reaches the app page route with its id encoded', () => {
  assert.equal(appPageHref('plugin:salesforce'), '/integrations/apps/plugin%3Asalesforce');
  assert.equal(appPageHref('con_1', 'tools'), '/integrations/apps/con_1?tab=tools');
});
