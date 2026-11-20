import assert from 'node:assert/strict';
import { test } from 'node:test';

import { onStaleSave, staleSave } from './save-base.ts';

const refused = (savedBy: string, version = 3) => ({ status: 409, code: 'stale_base', message: 'The draft was saved after it was read.', details: { version, savedBy, savedAt: '2026-11-19T14:02:00Z' } });

test('a save refused after the person’s own write is sent again with no message; another person’s save is said', () => {
  const own = staleSave(refused('kim@harborpine.example'));
  assert.deepEqual(own && onStaleSave(own, 'kim@harborpine.example', 3), { resend: true });
  // Her save is the newest, but under a later version number than the copy the page read: more was saved in between.
  const later = staleSave(refused('kim@harborpine.example', 4));
  assert.equal(later && onStaleSave(later, 'kim@harborpine.example', 3).resend, false);

  const theirs = staleSave(refused('lee@harborpine.example'));
  const told = theirs && onStaleSave(theirs, 'kim@harborpine.example', 3);
  assert.equal(told?.resend, false);
  assert.match(told && !told.resend ? told.note : '', /^lee@harborpine\.example saved a newer draft at \d/);
  // Who is signed in is not known yet: say it rather than send again over what may be another person's save.
  assert.equal(theirs && onStaleSave(theirs, undefined, 3).resend, false);

  // In review and deprecated are 409 too; only a stale base offers a reload.
  assert.equal(staleSave({ status: 409, code: 'review_open', message: 'In review.' }), null);
});
