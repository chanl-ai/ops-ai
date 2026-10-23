import assert from 'node:assert/strict';
import { test } from 'node:test';

import { errorKind, teamToUse } from './session-gate.ts';

// c-505: the tab remembered Security from an earlier sign-in, so the first requests after James signed in went out
// for a team he does not hold and the case page failed until a reload.
test('a remembered team the person does not hold gives way to their own team', () => {
  assert.equal(teamToUse('team_security', 'team_ops', ['team_ops']), 'team_ops');
  assert.equal(teamToUse('team_platform', null, ['team_fraud', 'team_ops']), 'team_fraud');
});

test('a team the person holds is kept, and nothing is chosen before their teams are known', () => {
  assert.equal(teamToUse('team_security', 'team_ops', ['team_ops', 'team_security']), 'team_security');
  assert.equal(teamToUse('team_ops', 'team_ops', []), null);
});

test('each failed status reads as its own state', () => {
  assert.deepEqual(
    [401, 403, 404, 500, 502, undefined].map((status) => errorKind(status === undefined ? new Error('network') : { status })),
    ['signed_out', 'forbidden', 'not_found', 'unavailable', 'unavailable', 'unavailable'],
  );
});
