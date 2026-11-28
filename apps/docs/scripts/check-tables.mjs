// A markdown table row must end on its own line: a row wrapped onto the next line renders as two rows with the
// second cell's text in the first column. Checks every .md under docs/ outside code fences.
import { readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';

const root = execSync('git rev-parse --show-toplevel').toString().trim();
const files = execSync("git ls-files 'docs/*.md' 'docs/**/*.md'", { cwd: root }).toString().split('\n').filter(Boolean);
const bad = [];
for (const f of files) {
  const lines = readFileSync(`${root}/${f}`, 'utf8').split('\n');
  let fence = false;
  lines.forEach((l, i) => {
    if (/^\s*```/.test(l)) fence = !fence;
    if (!fence && /^\|/.test(l) && !/\|\s*$/.test(l)) bad.push(`${f}:${i + 1}`);
  });
}
if (bad.length) {
  console.error(`check-tables: table row continues on the next line (join it into one line):\n  ${bad.join('\n  ')}`);
  process.exit(1);
}
console.log(`check-tables: ${files.length} pages, every table row on one line`);
