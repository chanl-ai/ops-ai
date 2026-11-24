import assert from 'node:assert/strict';
import { test } from 'node:test';

import { packFor } from './template-packs.ts';

test('skills point at the Starter skills pack page, which the Apps list does not hold', () => {
  assert.deepEqual(packFor('skill'), { name: 'Starter skills', href: '/data/connectors/plugin%3Aopsai.starters' });
});

test('a kind apps bring has no pack to point at', () => {
  assert.equal(packFor('agent'), null);
});
