// Where a skill's problems are drawn, by failure mode: a problem written under the wrong step, a second problem on a
// step that hides the first, and a refused save whose step is lost.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { PublishBlocker } from '@/lib/types/references';

import { placeProblems, refusedSave } from './skill-problems.ts';

const on = (step: number | null, kind: PublishBlocker['kind'], message: string, field = 'steps'): PublishBlocker => ({ kind, id: null, position: { field, step, index: null }, message });

test('problems are written under the step they name, joined when a step has two', () => {
  const placed = placeProblems([
    on(4, 'bad_check', 'The check reads a value no step returns.'),
    on(2, 'sub_skill_not_held', 'Verify identity is not published.'),
    on(4, 'bad_exit', 'needs_revew is not one of the endings.'),
    // The editor draws these with a fix row, so they are not written a second time.
    on(4, 'missing_reference', 'Step 4 names refund_card.'),
    on(null, 'bad_step', 'Not when names a tool.', 'notWhen'),
    { kind: 'unavailable_reference', id: null, position: null, message: 'Could not check the tools.' },
  ]);
  assert.deepEqual(placed, [
    { field: 'steps', step: 4, message: 'The check reads a value no step returns. needs_revew is not one of the endings.' },
    { field: 'steps', step: 2, message: 'Verify identity is not published.' },
  ]);
});

test('a save the service refuses for one step becomes a problem on that step, whatever its code, and any other refusal does not', () => {
  // The service's codes for a step are its own (bad_check, unknown_exit, bad_goto, sub_skill_cycle, unknown_reference).
  for (const code of ['bad_check', 'unknown_exit', 'sub_skill_cycle', 'unknown_reference'])
    assert.deepEqual(refusedSave({ status: 400, code, message: 'Step 3 cannot run.', details: { step: 3 } }), on(3, 'bad_step', 'Step 3 cannot run.'), code);
  assert.equal(refusedSave({ status: 400, code: 'validation_failed', message: 'steps.0.do: Field required' }), null);
  assert.equal(refusedSave({ status: 409, code: 'stale_base', message: 'v7 was saved after v6.', details: { step: 3 } }), null);
  assert.equal(refusedSave(new Error('offline')), null);
});
