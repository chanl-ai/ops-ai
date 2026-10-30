import assert from 'node:assert/strict';
import { test } from 'node:test';

import { activityStatus } from './activity-status.ts';

// #14 staging test: Activity's Status column mixed vocabularies. Every chat read "Idle" and a failed run read its End's
// outcome, "Not saved", in red. The column says one of five statuses; a row's own outcome is a note beside its title.
test('a failed run reads Failed, with its outcome as the note', () => {
  assert.deepEqual(activityStatus({ status: 'failed', outcome: 'not_saved', outcomeText: 'Not saved' }), { label: 'Failed', note: 'Not saved' });
});

test('a chat reads its status, never Idle', () => {
  assert.deepEqual(activityStatus({ status: 'done', outcome: 'idle', outcomeText: 'Idle' }), { label: 'Done', note: undefined });
});

test('an outcome that only repeats the status adds no note', () => {
  assert.deepEqual(activityStatus({ status: 'done', outcome: 'succeeded', outcomeText: 'Succeeded' }), { label: 'Done', note: undefined });
  assert.deepEqual(activityStatus({ status: 'failed', outcome: 'failed', outcomeText: 'Failed' }), { label: 'Failed', note: undefined });
});

test('an email set aside reads Skipped with why as the note', () => {
  assert.deepEqual(activityStatus({ status: 'skipped', outcome: 'set_aside', outcomeText: 'Set aside' }), { label: 'Skipped', note: 'Set aside' });
});
