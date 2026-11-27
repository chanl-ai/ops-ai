import assert from 'node:assert/strict';
import { test } from 'node:test';

import { listedOnPolicies, makersAskOf, makersAskSavable, requesterMayDecideOf } from './approval-rules.ts';

test('self-approval is read from the team’s own saved part, falling back to the workspace’s', () => {
  // As platform-service stores it after a team save.
  const stored = { '*': false, team_ops: true, team_risk: false };
  assert.equal(requesterMayDecideOf(stored, 'team_ops'), true);
  assert.equal(requesterMayDecideOf(stored, 'team_risk'), false);
  assert.equal(requesterMayDecideOf({ '*': true }, 'team_new'), true);
  assert.equal(requesterMayDecideOf({ team_ops: { agents: true } }, 'team_ops'), true);
  assert.equal(requesterMayDecideOf(true, 'team_ops'), true);
  assert.equal(requesterMayDecideOf(null, 'team_ops'), true);
});

test('Governance › Policies does not list the approvals floor', () => {
  assert.equal(listedOnPolicies('approvalsFloor'), false);
  assert.equal(listedOnPolicies('requesterMayDecide'), false);
  assert.equal(listedOnPolicies('egressNewHosts'), true);
});

// An unset makers' ask read as off let an admin press Save untouched and store off where the gateway had held every
// maker's ask: the form opens with no choice, and Save waits for one.
test('an unset makers ask opens with no choice and saves only once one is made', () => {
  const unset = makersAskOf({ ask: false, answer: 'person' });
  assert.deepEqual([unset, makersAskSavable(unset, unset), makersAskSavable(unset, false), makersAskSavable(unset, true)], [null, false, true, true]);
});

test('a saved makers ask saves only when changed', () => {
  assert.deepEqual([makersAskOf({ makersAsk: false }), makersAskSavable(false, false), makersAskSavable(false, true)], [false, false, true]);
});
