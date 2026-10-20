// The toast after a decision, by failure mode: a tool module publish reported as "The workflow run has resumed" (the
// UX walk's finding), and a publish request said to resume a run it never had.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { Review } from '@/lib/types/domain';

import { decisionToast } from './decision-toast.ts';

const base = { id: 'pr_1', title: 'Publish Statements v0.1.0', workflowName: 'Statements' } as Review;

test('a tool module publish names the module and version, and resumes nothing', () => {
  const t = decisionToast({ ...base, toolModule: { moduleId: 'mod_1', version: '0.1.0', applyPending: false } }, 'approved');
  assert.equal(t.title, 'Published Statements v0.1.0');
  assert.doesNotMatch(t.description, /resum/i);
});

test('only a paused step says the run resumed', () => {
  assert.doesNotMatch(decisionToast(base, 'approved').description, /resum/i);
  assert.match(decisionToast({ ...base, origin: { kind: 'workflow' } }, 'approved').description, /resumed/);
});
