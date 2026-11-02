import assert from 'node:assert/strict';
import { test } from 'node:test';

import { defaultShareMode, shareModes } from './share-form.ts';

test('without a public form page only team members can be offered', () => {
  assert.deepEqual(
    shareModes(false).map((m) => m.mode),
    ['members'],
  );
  assert.equal(defaultShareMode(false), 'members');
});

test('with a public form page a signed link is the default', () => {
  assert.deepEqual(
    shareModes(true).map((m) => m.mode),
    ['link', 'members'],
  );
  assert.equal(defaultShareMode(true), 'link');
});
