import assert from 'node:assert/strict';
import { test } from 'node:test';

import { versionLabel } from './version.ts';

test('a tagged build shows its tag, an untagged one its commit on main, and a build with neither shows nothing', () => {
  assert.equal(versionLabel('v2026-10-23.1', '1b4c3cd'), 'v2026-10-23.1');
  assert.equal(versionLabel('', '1b4c3cd'), 'main · 1b4c3cd');
  assert.equal(versionLabel(undefined, ' 1b4c3cd\n'), 'main · 1b4c3cd');
  assert.equal(versionLabel('', ''), null);
});
