import assert from 'node:assert/strict';
import { test } from 'node:test';

import { listedOnPolicies } from './approval-rules.ts';

test('Governance › Policies does not list the approvals floor or the retired self-approval key', () => {
  assert.equal(listedOnPolicies('approvalsFloor'), false);
  assert.equal(listedOnPolicies('requesterMayDecide'), false);
  assert.equal(listedOnPolicies('egressNewHosts'), true);
});
