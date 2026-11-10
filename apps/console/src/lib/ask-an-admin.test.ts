import assert from 'node:assert/strict';
import { test } from 'node:test';

import { askWhom } from './ask-an-admin.ts';

const dev = { name: 'Dev Admin', email: 'dev-admin@bank.example', inTeam: false };
const priya = { name: 'Priya Shah', email: 'p.shah@bank.example', inTeam: true };
const wanjiru = { name: 'Wanjiru Kamau', email: 'w.kamau@bank.example', inTeam: true };

test('the line names someone granted in the team, never an admin of every team, and counts the rest of the team', () => {
  const said = askWhom([dev, priya, wanjiru], 'r.menon@bank.example');
  assert.equal(said.first?.name, 'Priya Shah');
  assert.equal(said.more, 1);
});

test('with only admins of every team, the line names nobody', () => {
  const said = askWhom([dev], 'r.menon@bank.example');
  assert.equal(said.first, null);
  assert.deepEqual(said.all, [dev]);
});

test('the caller is never asked to ask themselves', () => {
  assert.equal(askWhom([priya, wanjiru], 'P.Shah@bank.example').first?.name, 'Wanjiru Kamau');
});
