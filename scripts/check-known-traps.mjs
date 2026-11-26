#!/usr/bin/env node
// Keeps each folder guide's "## Known traps" section short and usable. Agents read it before the first edit in a
// folder; a long section stops being read, and a line that names a trap without its fix gives the reader nothing to do.
//
// Format of a section (it runs to the next heading or the end of the file):
//   - at most 12 non-blank lines;
//   - every line is one list item, `- <trigger> => <fix>`: the separator is the three characters ` => ` (a space, an
//     equals sign, a greater-than sign, a space), with text before and after it. Wrap nothing: one trap, one line.
// Exit 1 lists every miss; run from the repo root (`make checks`, name `known-traps`). `--self-test` plants a 13-line
// section and a line with no fix and fails unless both are found.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';

export const MAX_LINES = 12;
const SEPARATOR = ' => ';

export function check(file, text) {
  const misses = [];
  const lines = text.split('\n');
  const start = lines.findIndex((l) => /^## Known traps\s*$/.test(l));
  if (start < 0) return misses;
  let end = lines.findIndex((l, i) => i > start && /^#{1,6}\s/.test(l));
  if (end < 0) end = lines.length;
  const body = lines.slice(start + 1, end).filter((l) => l.trim() !== '');
  if (body.length === 0) misses.push('Known traps is empty: delete the heading');
  if (body.length > MAX_LINES) misses.push(`Known traps has ${body.length} lines, the limit is ${MAX_LINES}`);
  for (const line of body) {
    if (!line.startsWith('- ')) { misses.push(`not a list item: ${line.slice(0, 60)}`); continue; }
    const at = line.indexOf(SEPARATOR);
    const trigger = at < 0 ? '' : line.slice(2, at).trim();
    const fix = at < 0 ? '' : line.slice(at + SEPARATOR.length).trim();
    if (!trigger || !fix) misses.push(`no fix part (write "<trigger>${SEPARATOR}<fix>"): ${line.slice(0, 60)}`);
  }
  return misses;
}

function selfTest() {
  const trap = (n) => `- Trigger ${n} => fix ${n}`;
  const guide = (lines) => `# Guide\n\n## Known traps\n\n${lines.join('\n')}\n\n## Next\n\n- not counted\n`;
  const many = (n) => Array.from({ length: n }, (_, i) => trap(i));
  const cases = [
    ['twelve lines pass', guide(many(12)), 0],
    ['thirteen lines fail', guide(many(13)), 1],
    ['a line with no fix fails', guide([trap(1), '- A trap with no fix part']), 1],
    ['an empty fix fails', guide(['- A trap => ']), 1],
    ['prose in the section fails', guide(['Some prose.']), 1],
    ['no section passes', '# Guide\n\n- anything\n', 0],
  ];
  const wrong = cases.filter(([, text, expect]) => (check('x', text).length > 0 ? 1 : 0) !== expect).map(([name]) => name);
  if (wrong.length) {
    console.error('check-known-traps self-test failed:', wrong);
    process.exit(1);
  }
  console.log(`check-known-traps self-test: ${cases.length} cases, the 13-line section and the line with no fix both fail`);
}

if (process.argv.includes('--self-test')) selfTest();
else {
  const files = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '*CLAUDE.md'], { encoding: 'utf8' })
    .split('\n').filter((f) => f && existsSync(f));
  let n = 0;
  for (const f of files) for (const miss of check(f, readFileSync(f, 'utf8'))) { console.error(`${f}: ${miss}`); n++; }
  console.log(`check-known-traps: ${files.length} guides, ${n} misses`);
  process.exit(n ? 1 : 0);
}
