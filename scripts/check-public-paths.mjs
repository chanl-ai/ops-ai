#!/usr/bin/env node
// Every file the public ops-ai repository receives names no path that stays private: the agent board's folder, the
// team's agent command sets and the session handoff (PRIVATE below). The publish step (the planning repo
// scripts/ops-ai/repo.sh, public_view.py) refuses a snapshot that does; this check refuses the commit first, with the
// same rule: such a path standing on its own, in any tracked file outside those folders. Cite docs/ instead. The paths
// are assembled below, never written out, so this file passes its own check and the publish step's.
// Usage: check-public-paths.mjs [--self-test]
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

// The folders and files that never leave (public-view-exclude.txt in the planning repo). Only hidden folders and whole
// file paths are matched in text: plain words such as `evidence/` also name object-store prefixes.
const dot = (name) => `.${name}/`;
const PRIVATE = [dot('codeloop'), dot('claude'), dot('cursor'), ['docs', 'agent-handoff.md'].join('/')];
const NEVER_SENT = [...PRIVATE, 'shape/', 'evidence/'];
// Ignore files name private folders on purpose; they point at nothing.
const IGNORE_FILE = /(^|\/)\.[a-z]*ignore$|\.dockerignore$/;
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const MENTION = new RegExp(`(?<![\\w/.-])(?:\\.\\./)*(?:\\./)?(?:${PRIVATE.map(escape).join('|')})`, 'g');

export function mentions(path, text) {
  if (IGNORE_FILE.test(path) || NEVER_SENT.some((p) => path === p || (p.endsWith('/') && path.startsWith(p)))) return [];
  const out = [];
  for (const m of text.matchAll(MENTION)) out.push(`${path}:${text.slice(0, m.index).split('\n').length}  ${text.slice(m.index).split(/[\s`'")\],;]/)[0].slice(0, 70)}`);
  return out;
}

function selfTest() {
  const [board, agents] = [dot('codeloop'), dot('claude')];
  const cases = [
    ['docs/a.md', `See \`${board}evidence/500/uc-red.txt\`.`, 1],
    ['services/x/m.py', `# (${board}wiki/decisions/x.md)`, 1],
    ['docs/a.md', `Linked from ../../${agents}commands/x.md`, 1],
    [`${board}wiki/a.md`, `${board}specs/x`, 0],
    ['.gitignore', board, 0],
    [`apps/x/${agents}settings.json`, `apps/x/${agents}settings.json`, 0],
    ['docs/a.md', 'evidenceDir("500", "uc")', 0],
  ];
  const bad = cases.filter(([p, t, n]) => mentions(p, t).length !== n);
  for (const c of bad) console.log(`FAIL ${c[0]}: ${JSON.stringify(c[1])} expected ${c[2]}`);
  return bad.length === 0;
}

if (process.argv.includes('--self-test')) process.exit(selfTest() ? 0 : 1);
const files = execFileSync('git', ['ls-files', '-z'], { encoding: 'utf8', maxBuffer: 64 << 20 }).split('\0').filter(Boolean);
const hits = [];
for (const f of files) {
  let text;
  try {
    text = readFileSync(f, 'utf8');
  } catch {
    continue;
  }
  if (text.includes('\0')) continue;
  hits.push(...mentions(f, text));
}
if (hits.length) {
  console.error(`check-public-paths: ${hits.length} private path(s) in files the public repo receives; cite docs/ instead:\n${hits.map((h) => `  ${h}`).join('\n')}`);
  process.exit(1);
}
console.log(`check-public-paths: ${files.length} files clean`);
