#!/usr/bin/env node
// Writes docs/diagrams/<name>.svg from each docs/diagrams/<name>.yaml, the same drawing the site renders live, so
// GitHub shows the diagram too. `--check` writes nothing and fails when a committed SVG is out of date.
import fs from 'node:fs';
import path from 'node:path';

import yaml from 'js-yaml';

import { renderBoxDiagram } from '../src/lib/box-diagram.mjs';
import { repoRoot } from '../src/lib/repo.mjs';

const dir = path.join(repoRoot(), 'docs/diagrams');
const check = process.argv.includes('--check');
const stale = [];
for (const f of fs.readdirSync(dir).filter((n) => n.endsWith('.yaml')).sort()) {
  const svg = `${renderBoxDiagram(yaml.load(fs.readFileSync(path.join(dir, f), 'utf8')), { standalone: true })}\n`;
  const out = path.join(dir, f.replace(/\.yaml$/, '.svg'));
  const current = fs.existsSync(out) ? fs.readFileSync(out, 'utf8') : '';
  if (current === svg) continue;
  if (check) stale.push(path.relative(repoRoot(), out));
  else {
    fs.writeFileSync(out, svg);
    console.log(`diagrams: wrote ${path.relative(repoRoot(), out)}`);
  }
}
if (stale.length) {
  console.error(`diagrams: out of date, run \`pnpm --filter docs diagrams\`:\n  ${stale.join('\n  ')}`);
  process.exit(1);
}
if (check) console.log('diagrams: every SVG matches its data file');
