import assert from 'node:assert/strict';
import { test } from 'node:test';

import { DAYS, formOf, ruleOf } from './every-rule.ts';

test('a Monday to Friday rule with hours reopens as it was saved, and every day is sent as no days', () => {
  const weekdays = ruleOf({ ...formOf(undefined), every: '15', unit: 'minutes', start: '07:00', days: ['mon', 'tue', 'wed', 'thu', 'fri'], from: '07:00', to: '18:00', tz: 'Europe/London' });
  assert.deepEqual(weekdays, { kind: 'every', every: 15, unit: 'minutes', start: '07:00', days: ['mon', 'tue', 'wed', 'thu', 'fri'], between: ['07:00', '18:00'], tz: 'Europe/London' });
  assert.deepEqual(ruleOf(formOf(weekdays)), weekdays);
  // All seven ticked is the same rule as no days: it must not come back as a different one.
  const every = ruleOf({ ...formOf(undefined), days: [...DAYS], tz: 'UTC' });
  assert.equal('days' in every, false);
  assert.deepEqual(formOf(every).days, [...DAYS]);
  // A half-filled window is not sent as one: the server would refuse a single time.
  assert.equal('between' in ruleOf({ ...formOf(undefined), from: '07:00', to: '' }), false);
});
