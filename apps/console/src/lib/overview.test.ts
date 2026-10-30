import assert from 'node:assert/strict';
import { test } from 'node:test';

import { hintsFrom, readOverview } from './overview.ts';

test('an overview from an older agents-service, with no counts or lists, reads as empty instead of crashing', () => {
  const older = { openReviews: 3, overdueReviews: 0, urgentReviews: [], cases: { open: 1, breaching: 0, awaitingApproval: 0 } };
  assert.deepEqual(readOverview(older), { counts: { waitingForMe: 0, runsInFlight: 0, casesDue: 0 }, waitingForMe: [], runsInFlight: [], casesDue: [] });
  assert.deepEqual(hintsFrom(older), []);
  assert.deepEqual(hintsFrom(undefined), []);
});

test('hints take the first task, case and run, one of each, with the case read as late once its deadline passed', () => {
  const now = Date.parse('2026-10-28T12:00:00Z');
  const hints = hintsFrom(
    {
      waitingForMe: [{ id: 'r1', title: 'Refund for Marcus Bell', createdAt: '2026-10-28T11:00:00Z' }, { id: 'r2', title: 'Second', createdAt: '2026-10-28T11:30:00Z' }],
      casesDue: [{ id: 'c1', subject: 'Chargeback evidence', status: 'open', resolutionDueAt: '2026-10-28T10:00:00Z' }],
      runsInFlight: [{ id: 'w1', workflowId: 'wf', subject: 'Card dispute intake', state: 'waiting', startedAt: '2026-10-28T09:00:00Z' }],
    },
    now,
  );
  assert.deepEqual(hints.map((h) => [h.id, h.label, h.detail]), [
    ['task', 'Refund for Marcus Bell', 'Human Task waiting for you since 1h ago'],
    ['case', 'Chargeback evidence', 'Case past its deadline'],
    ['run', 'Card dispute intake', 'Run waiting on a person'],
  ]);
});
