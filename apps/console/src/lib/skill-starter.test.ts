import assert from 'node:assert/strict';
import test from 'node:test';

import { WORKED_EXAMPLE } from './skill-starter.ts';

test('the starter text shows a tool step, then an if path with its else, each indented under it', () => {
  const lines = WORKED_EXAMPLE.split('\n');
  const at = (re: RegExp) => lines.findIndex((l) => re.test(l));
  assert.match(lines[0], /type @/);
  assert.ok(at(/^if .*:$/) > 0 && at(/^else:$/) > at(/^if .*:$/), 'an if line, then its else at the same indent');
  assert.ok(lines.every((l, i) => !/^(if|else)\b/.test(l) || /^\s{4}\S/.test(lines[i + 1] ?? '')), 'each path has an indented line under it');
});
