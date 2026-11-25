import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ssoReturn } from './sso-return.ts';

test('link_required is told apart from every other refusal, and a code is not a refusal', () => {
  const of = (q: string) => ssoReturn(new URLSearchParams(q));
  assert.equal(of('error=link_required&next=%2Fchat'), 'link_required');
  assert.equal(of('error=no_access'), 'refused');
  assert.equal(of('error=sign_in_refused'), 'refused');
  assert.equal(of('code=abc'), 'code');
});
