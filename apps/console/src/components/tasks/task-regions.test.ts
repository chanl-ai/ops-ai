import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { Review } from '../../lib/types/domain.ts';
import { proposalNodes, taskView } from './task-regions.ts';

const conflicts = JSON.stringify({
  conflicts: [{ field: 'case_no', values: [{ source: 'attachment', value: 'NS-2026-GN-01187' }, { source: 'email', value: 'NS-2026-GN-01188' }] }],
});

test('a workflow step whose proposal holds two disagreeing values shows both on the task', () => {
  const view = taskView({ id: 'r1', title: 'The email and its attachment disagree', proposal: conflicts, workflowName: 'Mail' } as unknown as Review);
  const text = JSON.stringify(view.decide);
  assert.ok(text.includes('NS-2026-GN-01187') && text.includes('NS-2026-GN-01188'), text);
});

test('a held action whose proposal is plain JSON fields draws no proposal cards', () => {
  const view = taskView({ id: 'r2', title: 'Hold', proposal: '{"account":"CHQ-2219","amount":2000}', question: 'Hold it?', options: [], consequence: 'x' } as unknown as Review);
  const text = JSON.stringify(view.decide);
  assert.ok(!text.includes('Account') && !text.includes('CHQ-2219'), text);
});

test('a typed task whose proposal is a plain step summary shows no proposal cards', () => {
  const proposal = JSON.stringify({ moduleId: 'mod_core_banking', approvalId: 'ap_1', deciderTeam: 'team_platform', expiresAt: '2026-11-12T09:00:00Z' });
  const task = { type: { id: 'tool_access', version: 1, name: 'Tool access request' }, regions: [{ region: 'header', data: { title: 'Tool access request' } }], actions: [], warnings: [] };
  const view = taskView({ id: 'r3', title: 'Tool access request', proposal, task } as unknown as Review);
  const text = JSON.stringify(view.decide);
  assert.ok(!text.includes('mod_core_banking') && !text.includes('team_platform') && !text.includes('2026-11-12'), text);
});

test('a proposal that is a sentence, or malformed JSON, adds nothing', () => {
  assert.deepEqual(proposalNodes('Place a 24-hour hold'), []);
  assert.deepEqual(proposalNodes('{not json'), []);
});
