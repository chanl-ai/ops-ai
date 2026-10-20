// A purpose files-service adds shows a blank Purpose on Files and no row on Storage until the console names it. The
// contract is the files-service OpenAPI document, so a new purpose there fails here first.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { PURPOSE_LABEL, STORED_PURPOSES } from './file-purposes.ts';

function contractPurposes(): Set<string> {
  const doc: unknown = JSON.parse(readFileSync(new URL('../../../../services/files-service/openapi.json', import.meta.url), 'utf8'));
  const found = new Set<string>();
  const walk = (o: unknown): void => {
    if (Array.isArray(o)) return o.forEach(walk);
    if (o && typeof o === 'object') {
      const e = (o as { enum?: unknown }).enum;
      if (Array.isArray(e) && e.includes('knowledge_source')) e.forEach((v) => found.add(String(v)));
      Object.values(o).forEach(walk);
    }
  };
  walk(doc);
  return found;
}

test('every purpose the files contract lists has a label', () => {
  const purposes = contractPurposes();
  assert.ok(purposes.size > 0, 'no purpose enum found in the files contract');
  assert.deepEqual([...purposes].filter((p) => !(p in PURPOSE_LABEL) || !PURPOSE_LABEL[p as keyof typeof PURPOSE_LABEL]), []);
});

test('the Storage page offers a target for every purpose files-service stores', () => {
  assert.deepEqual([...STORED_PURPOSES].sort(), [...contractPurposes()].sort());
});
