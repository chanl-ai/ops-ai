import assert from 'node:assert/strict';
import { test } from 'node:test';

import { NAME_MESSAGES, nameProblem, slugify } from './names.ts';

// The values ops_service_kit.names gives for the same input; a drift between the two copies fails here.
test('the console names give the kit slugs and refusals', () => {
  assert.deepEqual(
    [
      slugify('QA 高风险交易审查'),
      slugify('QA 客户投诉处理'),
      slugify('Проверка переводов', { fallback: 'agent' }),
      slugify('Zürich Desk'),
      slugify('سلام', { sep: '_' }),
      slugify('Sweden Central', { sep: '' }),
      slugify('Wire review '.repeat(16), { reserve: 5 }).length,
    ],
    ['qa-e1bdc449', 'qa-5effbf94', 'agent-169f2ea7', 'zurich-desk', '86f13bb6', 'swedencentral', 115],
  );
  assert.deepEqual(
    ['​', 'Wire\nreview', 'Wire\u0000review', ' Wire\treview '].map((n) => nameProblem(n)),
    [NAME_MESSAGES.blank, NAME_MESSAGES.lineBreak, NAME_MESSAGES.control, undefined],
  );
});
