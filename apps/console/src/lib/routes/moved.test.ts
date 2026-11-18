import assert from 'node:assert/strict';
import { test } from 'node:test';

import { movedTo } from './moved.ts';

test('an old sources address reaches the sources list in Knowledge, and an old source page that source', () => {
  assert.equal(movedTo('/integrations/sources'), '/data/knowledge');
  assert.equal(movedTo('/integrations/sources/src_1'), '/data/sources/src_1');
  assert.equal(movedTo('/integrations/sources/src_1/items'), '/data/sources/src_1/items');
});
