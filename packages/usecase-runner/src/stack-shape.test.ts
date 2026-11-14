// A ui use case runs on the services the real stack runs: platform-service signs the console in unless the script
// opts out, and a script that never mentioned sign-in gets the dev builder signed in for it, as the mock did.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { resolveStack } from './harness.ts';

test('platform-service starts unless a script opts out, and only a script that left sign-in alone is signed in for', () => {
  const left = resolveStack({});
  assert.equal(left.options.platform, true);
  assert.equal(left.signedInAs, 'builder');

  // A page whose rows belong to another team is opened by that team's dev person.
  assert.equal(resolveStack({ signedInAs: 'platform' }).signedInAs, 'platform');

  const tools = resolveStack({ tools: {} });
  assert.deepEqual([tools.options.platform, tools.signedInAs, tools.options.tools], [true, 'builder', {}]);

  // A script that says platform signs in on /login itself, so a stored session would send it past the form.
  assert.equal(resolveStack({ platform: true }).signedInAs, null);
  assert.equal(resolveStack({ demo: true }).signedInAs, null);

  const off = resolveStack({ platform: false });
  assert.deepEqual([off.options.platform, off.signedInAs], [false, null]);
});
