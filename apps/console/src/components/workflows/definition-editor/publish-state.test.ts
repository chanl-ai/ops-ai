import assert from 'node:assert/strict';
import { test } from 'node:test';

import { canSubmitPublish } from './publish-state.ts';

const block = { node: 'start', level: 'error', code: 'mailbox_not_offered', message: 'fraud@bank.example is team_fraud’s mailbox', field: 'mailbox' };

test('Send for review is disabled while a blocker is listed, and enabled once none is', () => {
  const preview = { reviewRequired: true, blockers: [block] };
  assert.equal(canSubmitPublish(preview, false), false);
  assert.equal(canSubmitPublish({ ...preview, blockers: [] }, false), true);
  assert.equal(canSubmitPublish(undefined, false), false);
});
