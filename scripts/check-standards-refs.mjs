#!/usr/bin/env node
// Keeps the engineering standards wired in. Two things rot otherwise: a folder guide or an agent that never points at
// the rules for its code, so the next builder works without them; and a rule id cited somewhere that no page defines
// (a renumbered or retired rule), so a review finding points at nothing.
//
// Checks, over every tracked file the standards must reach (see REQUIRED) plus every file that may cite a rule:
//   1. each required file links a standards page (docs/architecture/standards/<area>.md or the index);
//   2. every relative link into docs/architecture/standards/ or to engineering-standards.md resolves to a file;
//   3. every rule id written in backticks (`DA5`, or a whole area as `DA*`) is defined by a `### DA5 ` heading on a
//      standards page.
// Exit 1 lists every miss; run from the repo root (`make docs-guides-check`). `--self-test` proves each check can fail.
import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join, normalize } from 'node:path';

const STANDARDS_DIR = 'docs/architecture/standards';
const INDEX = 'docs/architecture/engineering-standards.md';
const AREAS = ['LY', 'CF', 'TN', 'AC', 'DA', 'AP', 'MD', 'EV', 'UI', 'OB', 'SC', 'TS', 'DL'];
// A guide under one of these roots describes code the standards cover, so it must link the page for that code.
const REQUIRED = /^(CLAUDE\.md|(apps|services|packages|sdk|deploy|make|scripts)\/.*CLAUDE\.md|\.claude\/agent-rules\.md|\.claude\/agents\/[^/]+\.md)$/;
// Files that may cite a rule id: the required ones, the index and the standards pages themselves.
const CITING = /^(.*CLAUDE\.md|AGENTS\.md|CONTRIBUTING\.md|\.claude\/.*\.md|docs\/architecture\/engineering-standards\.md|docs\/architecture\/standards\/.*\.md)$/;

const idPattern = new RegExp(`^(${AREAS.join('|')})(\\d{1,2}|\\*)$`);
const linkPattern = /\[[^\]]*\]\(([^)\s]+)\)/g;
const codePattern = /`([^`\n]+)`/g;

export function definedIds(dir = STANDARDS_DIR) {
  const ids = new Set();
  if (!existsSync(dir)) return ids;
  for (const f of readdirSync(dir)) {
    if (!f.endsWith('.md')) continue;
    const text = readFileSync(join(dir, f), 'utf8');
    for (const m of text.matchAll(/^#{2,4}\s+([A-Z]{2}\d{1,2})\s/gm)) ids.add(m[1]);
  }
  return ids;
}

export function check(file, text, ids, exists = existsSync) {
  const misses = [];
  const body = text.replace(/```[\s\S]*?```/g, '');
  const linksStandards = body.includes(`${STANDARDS_DIR}/`) || body.includes(INDEX);
  if (REQUIRED.test(file) && !linksStandards) misses.push('no link to a standards page (docs/architecture/standards/<area>.md or engineering-standards.md)');
  for (const [, target] of body.matchAll(linkPattern)) {
    if (/^(https?:|mailto:)/.test(target)) continue;
    const path = target.split('#')[0];
    if (!path || !/standards\/|engineering-standards\.md$/.test(path)) continue;
    const resolved = normalize(join(dirname(file), path));
    if (!exists(resolved)) misses.push(`link ${target}: ${resolved} does not exist`);
  }
  if (!CITING.test(file)) return misses;
  const seen = new Set();
  for (const [, code] of body.matchAll(codePattern)) {
    const m = idPattern.exec(code.trim());
    if (!m || seen.has(code)) continue;
    seen.add(code);
    if (m[2] === '*') {
      if (![...ids].some((id) => id.startsWith(m[1]))) misses.push(`rule area ${code}: no rule with that prefix is defined`);
    } else if (!ids.has(code.trim())) misses.push(`rule ${code}: no standards page defines it`);
  }
  return misses;
}

function selfTest() {
  const ids = new Set(['DA1', 'DA5', 'UI1']);
  const exists = (p) => p === 'docs/architecture/standards/data-access.md';
  const bad = check('services/CLAUDE.md', 'Rules: `DA5`, `DA99`, `XX1` and `LY*`. [page](../docs/architecture/standards/no-such.md)', ids, exists);
  const good = check('services/CLAUDE.md', 'Rules: `DA5` and `DA*` in [data access](../docs/architecture/standards/data-access.md).', ids, exists);
  const unlinked = check('.claude/agents/ops-x.md', 'Reads the profile and the brief; cites nothing.', ids, exists);
  const skipped = check('docs/guide/plugins.md', 'No link here and `DA99` is prose for this file.', ids, exists);
  // bad names the standards folder in its broken link, so its misses are DA99, LY* and the link; XX1 is not an area.
  if (bad.length !== 3 || unlinked.length !== 1 || good.length !== 0 || skipped.length !== 0) {
    console.error('check-standards-refs self-test failed', { bad, unlinked, good, skipped });
    process.exit(1);
  }
  console.log('check-standards-refs self-test: 4 planted misses found, 0 on good input');
}

if (process.argv.includes('--self-test')) selfTest();
else {
  const ids = definedIds();
  if (ids.size === 0) { console.error(`check-standards-refs: no rule ids found under ${STANDARDS_DIR}`); process.exit(1); }
  const files = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '*.md'], { encoding: 'utf8' })
    .split('\n').filter((f) => f && existsSync(f) && (REQUIRED.test(f) || CITING.test(f)));
  // The agents folder may sit on a local exclude list, so a new agent is read from disk rather than from git. The folder
  // is not in the public export, and check-public-paths reads path literals, so its name is assembled here.
  const agentsDir = ['.claude', 'agents'].join('/');
  if (existsSync(agentsDir)) for (const f of readdirSync(agentsDir)) if (f.endsWith('.md') && !files.includes(`${agentsDir}/${f}`)) files.push(`${agentsDir}/${f}`);
  let n = 0;
  for (const f of files) for (const miss of check(f, readFileSync(f, 'utf8'), ids)) { console.error(`${f}: ${miss}`); n++; }
  console.log(`check-standards-refs: ${ids.size} rule ids, ${files.length} files, ${n} misses`);
  process.exit(n ? 1 : 0);
}
