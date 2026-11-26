import assert from 'node:assert/strict';
import { test } from 'node:test';

import { lastRunWords } from './schedule-words.ts';

test('a skipped last run reads with its reason in the schedule\'s zone and links its run; one never run says so', () => {
  const skipped = lastRunWords({ lastOutcome: 'skipped', lastSlotAt: '2026-11-23T10:15:00Z', lastOutcomeReason: 'The last scheduled run was still going.', lastRunId: 'wfrun_1' }, 'Asia/Tokyo');
  assert.equal(skipped.text, 'Nov 23, 19:15 · skipped: The last scheduled run was still going.');
  assert.equal(skipped.runHref, '/build/runs/wfrun_1');
  assert.deepEqual(lastRunWords({ lastOutcome: null, lastSlotAt: null, lastOutcomeReason: null, lastRunId: null }), { text: 'Not run yet.', runHref: null });
});
