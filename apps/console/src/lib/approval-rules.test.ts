import assert from 'node:assert/strict';
import { test } from 'node:test';

import { listedOnPolicies, requesterMayDecideOf } from './approval-rules.ts';

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
