import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MODEL_PROVIDERS_HREF, modelRefusal } from './model-refusals.ts';

const PROVIDER_CODES = ['provider_unreachable', 'provider_timeout', 'provider_auth_failed', 'provider_rate_limited', 'provider_bad_request', 'provider_error', 'provider_key_missing'];

test('every way a provider fails has its own sentence, never the generic refusal', () => {
  const said = PROVIDER_CODES.map((c) => modelRefusal(c, false)?.text);
  assert.ok(said.every(Boolean), `a code has no sentence: ${PROVIDER_CODES[said.findIndex((s) => !s)]}`);
  assert.equal(new Set(said).size, PROVIDER_CODES.length, 'two failures read the same');
});

test('a refused key tells an admin to fix it there and anyone else to ask an admin', () => {
  const admin = modelRefusal('provider_auth_failed', true);
  const member = modelRefusal('provider_auth_failed', false);
  assert.match(admin!.text, /^The model provider refused the account’?'?s key\. Check or replace the key on Settings > Model providers\.$/);
  assert.equal(admin!.fixAt, MODEL_PROVIDERS_HREF);
  assert.match(member!.text, /Ask an admin to check the key on Settings > Model providers\./);
  assert.equal(member!.fixAt, undefined, 'a member is not sent to a page they cannot change');
});

test('a code the console does not word is left to the service message', () => {
  assert.equal(modelRefusal('something_new', true), undefined);
  assert.equal(modelRefusal(undefined, false), undefined);
});
