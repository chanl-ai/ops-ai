import assert from 'node:assert/strict';
import { test } from 'node:test';

import { onStaleSave, staleSave } from './save-base.ts';

const refused = (savedBy: string) => ({ status: 409, code: 'stale_base', message: 'The draft was saved after it was read.', details: { version: 3, savedBy, savedAt: '2026-11-19T14:02:00Z' } });

test('a save refused after the person’s own write is sent again with no message; another person’s save is said', () => {
  const own = staleSave(refused('kim@harborpine.example'));
  assert.deepEqual(own && onStaleSave(own, 'kim@harborpine.example'), { resend: true });

  const theirs = staleSave(refused('lee@harborpine.example'));
  const told = theirs && onStaleSave(theirs, 'kim@harborpine.example');
  assert.equal(told?.resend, false);
  assert.match(told && !told.resend ? told.note : '', /^lee@harborpine\.example saved a newer draft at \d/);
  // Who is signed in is not known yet: say it rather than send again over what may be another person's save.
  assert.equal(theirs && onStaleSave(theirs, undefined).resend, false);

  // In review and deprecated are 409 too; only a stale base offers a reload.
  assert.equal(staleSave({ status: 409, code: 'review_open', message: 'In review.' }), null);
});
