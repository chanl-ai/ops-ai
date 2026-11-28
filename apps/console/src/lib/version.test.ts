import assert from 'node:assert/strict';
import { test } from 'node:test';

import { versionLabel } from './version.ts';

test('a tagged build shows its tag, an untagged one its branch and commit, and a build with neither shows nothing', () => {
  assert.equal(versionLabel('v1.2.0-rc.1', '1b4c3cd', 'develop'), 'v1.2.0-rc.1');
  assert.equal(versionLabel('', '1b4c3cd', 'feat/console-editor'), 'feat/console-editor · 1b4c3cd');
  assert.equal(versionLabel(undefined, ' 1b4c3cd\n', ''), '1b4c3cd');
  assert.equal(versionLabel('', ''), null);
});
