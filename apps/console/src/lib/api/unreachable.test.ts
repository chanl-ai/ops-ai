import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createPlatformProvider } from '../auth/providers/platform.ts';
import { isUnreachable } from './unreachable.ts';

/** Sign-in through the real provider against a platform that answers `status`, or never answers; returns what it threw. */
async function signInError(answer: number | 'no answer'): Promise<unknown> {
  globalThis.fetch = (async () => {
    if (answer === 'no answer') throw new TypeError('Failed to fetch');
    return Response.json({ success: false, error: { code: 'x', message: 'Sign in again.', status: answer } }, { status: answer });
  }) as typeof fetch;
  try {
    await createPlatformProvider('http://platform').signInWithPassword('j.richardson@harborpine.example', 'wrong');
  } catch (e) {
    return e;
  }
  assert.fail('sign-in did not throw');
}

test('a wrong password is an answer, not an outage, and says to check the email and password', async () => {
  const wrong = await signInError(401);
  assert.equal(isUnreachable(wrong), false);
  assert.equal((wrong as Error).message, 'Sign-in failed. Check the email and password.');
  assert.equal(isUnreachable(await signInError(403)), false);
});

test('a 5xx or no answer from sign-in is an outage', async () => {
  assert.equal(isUnreachable(await signInError(503)), true);
  assert.equal(isUnreachable(await signInError('no answer')), true);
});
