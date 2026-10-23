import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { CaseRecordDetail } from '@/lib/types/case-records';
import type { Review } from '@/lib/types/domain';
import type { EngineRunDetail } from '@/lib/types/engine';

import { caseCard, missingCard, runCard, taskCard, taskDecision } from './ops-card-mappers.ts';

const review = (over: Partial<Review>): Review =>
  ({ id: 'rv_1', title: 'Give Priya Nair a provisional credit?', status: 'pending', canDecide: true, kind: 'action', customer: 'Priya Nair', workflowName: 'Card dispute', amount: 412.5, currency: 'CAD', createdAt: '2026-10-22T10:00:00Z', policy: { reviewers: 'Dispute reviewers' }, ...over }) as unknown as Review;

test('a Human Task offers its decision only while open, to a person who may decide it, as a plain approve or reject', () => {
  assert.equal(taskDecision(review({})), 'buttons');
  assert.equal(taskDecision(review({ canDecide: false })), 'open-only');
  assert.equal(taskDecision(review({ options: [{ name: 'hold' }] as unknown as Review['options'] })), 'open-only');
  assert.equal(taskDecision(review({ status: 'approved', decidedBy: 'Maya Okafor' })), 'decided');
});

test('a decided task names who decided it, and an amount that needs a step-up is the fact the decision turns on', () => {
  assert.equal(taskCard(review({ status: 'approved', decidedBy: 'Maya Okafor' })).status?.text, 'Approved by Maya Okafor');
  const money = taskCard(review({ stepUp: true }));
  const amount = money.body.kind === 'facts' ? money.body.facts.find((f) => f.label === 'Amount') : undefined;
  assert.equal(amount?.warn, true);
  assert.match(amount?.value ?? '', /412\.50/);
});

test('cards never show raw JSON or engine keys', () => {
  const c = caseCard({ id: 'case_1', subject: 'Charged twice', status: 'waiting_on_customer', priority: 'high', customerName: 'Marcus Bell', assignee: null, resolutionDueAt: '2026-10-25T10:00:00Z', resolutionLeftS: 3600 } as unknown as CaseRecordDetail);
  const r = runCard({ id: 'wfrun_1', workflowId: 'card_dispute_intake', status: 'waiting', story: { lines: [{ text: 'Read the dispute email.' }] } } as unknown as EngineRunDetail);
  const shown = [c.status?.text, r.status?.text, r.title, ...(c.body.kind === 'facts' ? c.body.facts.map((f) => f.value) : []), ...(r.body.kind === 'steps' ? r.body.steps.map((s) => s.title) : [])];
  for (const text of shown) {
    assert.ok(text && !/[{}]|\b[a-z]+_[a-z_]+\b/.test(text), `shown as typed by the engine: ${text}`);
  }
  assert.deepEqual([c.status?.text, r.title], ['Waiting on the customer', 'Card dispute intake']);
});

test('a reference the reader cannot see says so and offers nothing', () => {
  const m = missingCard({ type: 'case', id: 'case_gone', missing: true });
  assert.match(m.title, /isn’t available to you/);
  assert.equal(m.body.kind, 'none');
});

test('a step that proposes data, not a sentence, does not show it as the proposal', () => {
  const card = taskCard(review({ proposal: '{"dispute": {"cardholder": "Marcus Bell"}}' }));
  assert.ok(card.body.kind === 'facts' && !card.body.facts.some((f) => f.label === 'Proposed'), JSON.stringify(card.body));
});
