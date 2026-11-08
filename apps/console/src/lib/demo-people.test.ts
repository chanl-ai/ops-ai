import assert from 'node:assert/strict';
import { test } from 'node:test';

import { demoPeopleByTeam } from './demo-people.ts';

test('the picker lists each team once, a person under every team they are in', () => {
  const groups = demoPeopleByTeam([
    { name: 'Priya', email: 'p@x', teams: [{ team: 'Operations', role: 'admin' }, { team: 'Security', role: 'admin' }] },
    { name: 'Ravi', email: 'r@x', teams: [{ team: 'Operations', role: 'viewer' }] },
    { name: 'Helena', email: 'h@x', teams: [{ team: 'Wealth Advisory', role: 'admin' }] },
  ]);
  assert.deepEqual(groups.map((g) => [g.team, g.people.map((p) => `${p.name}:${p.role}`)]), [
    ['Operations', ['Priya:admin', 'Ravi:viewer']],
    ['Security', ['Priya:admin']],
    ['Wealth Advisory', ['Helena:admin']],
  ]);
});
