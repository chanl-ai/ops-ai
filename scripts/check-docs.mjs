#!/usr/bin/env node
// Enforces where documentation lives (CONTRIBUTING.md, "Where docs live"). Full docs live only under docs/, in a
// folder that maps to a part of the repo. Code folders carry a short README that points into docs/.
// Exit 1 lists every violation; run from the repo root.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';

// media holds the README's screenshots and clips (docs/usecases/lib/capture_demo.mjs writes them); diagrams holds the
// architecture diagrams' data files and their exported SVGs (apps/docs draws them).
const DOC_FOLDERS = ['background', 'architecture', 'design', 'console', 'services', 'packages', 'deploy', 'guide', 'plan', 'artifacts', 'usecases', 'media', 'diagrams', 'sdk'];
// Use case scripts and their shared harness live beside the use case docs; only the docs follow the naming rules.
const USECASE_CODE = /^docs\/usecases\/(lib|[a-z0-9-]+\/scripts)\/[^/]+\.(py|mjs)$/;
// Mapped folders: docs/services/<x> needs services/<x>, docs/packages/<x> needs packages/<x>.
const MAPPED = ['services', 'packages'];
const ROOT_FILES = new Set(['README.md', 'CLAUDE.md', 'AGENTS.md', 'CONTRIBUTING.md', 'CHANGELOG.md']);
const BRIEF_NAMES = new Set(['README.md', 'CLAUDE.md', 'AGENTS.md']);
// Agent working state, not documentation.
const IGNORED = /^(\.codeloop|\.claude|\.cursor|shape|specs|evidence|services\/[^/]+\/seed)\//; // evidence/<nnn>/ holds a card's review and verify records, which belong to the card, not to docs/; a service's seed/ holds demo data (documents a knowledge base indexes), not documentation
// Copilot's files, generated from docs/guide/skills/ by scripts/agent_skills.py (c-554); their source is the doc.
const GENERATED = /^\.github\/(prompts\/[^/]+\.prompt\.md|copilot-instructions\.md)$/;
const BRIEF_MAX_LINES = 40;

const DATED = /(^|\/)\d{4}-\d{2}-\d{2}[-_.]/;
// Topic names only: a number or sequence prefix (01-, ADR-0001-, E2-) fails; ids live in the title.
const KEBAB = /^[a-z][a-z0-9]*(-[a-z0-9]+)*\.(md|html|pdf|png|svg|gif|yaml)$/;

const files = execFileSync('git', ['ls-files', '--cached'], { encoding: 'utf8' })
  .split('\n')
  .filter((f) => f && !IGNORED.test(f) && !GENERATED.test(f) && existsSync(f));

const problems = [];
const fail = (file, why) => problems.push(`${file}: ${why}`);

const docsIndex = existsSync('docs/README.md') ? readFileSync('docs/README.md', 'utf8') : '';

for (const file of files) {
  const name = file.split('/').pop();
  const isMd = name.endsWith('.md');

  if (DATED.test(file)) fail(file, 'date in the name; name the topic and keep history in git');

  if (file.startsWith('docs/')) {
    const parts = file.split('/');
    if (parts.length > 2) {
      const top = parts[1];
      if (!DOC_FOLDERS.includes(top)) fail(file, `docs/${top}/ is not a mapped folder (${DOC_FOLDERS.join(', ')})`);
      if (MAPPED.includes(top) && parts.length > 3 && !statSafe(`${top}/${parts[2]}`)) {
        fail(file, `docs/${top}/${parts[2]}/ has no matching ${top}/${parts[2]}/ in the repo`);
      }
    }
    if (top(file) === 'artifacts' || USECASE_CODE.test(file)) continue;
    if (name !== 'README.md' && !KEBAB.test(name)) fail(file, 'file name is not a kebab-case topic (no number, date or sequence prefix)');
    if (isMd) {
      const head = readFileSync(file, 'utf8').split('\n').slice(0, 15).join('\n');
      if (!/^Status:/m.test(head)) fail(file, 'no "Status:" line near the top');
      const rel = file.slice('docs/'.length);
      if (file !== 'docs/README.md' && !docsIndex.includes(rel)) fail(file, 'not listed in docs/README.md');
    }
    continue;
  }

  if (!isMd) continue;
  if (!file.includes('/')) {
    if (!ROOT_FILES.has(name)) fail(file, 'only README, CLAUDE, AGENTS, CONTRIBUTING and CHANGELOG live at the root; move it under docs/');
    continue;
  }
  if (!BRIEF_NAMES.has(name)) {
    fail(file, 'documentation outside docs/; move it to the matching docs/ folder and link to it from the README');
    continue;
  }
  if (name === 'README.md') {
    const text = readFileSync(file, 'utf8');
    const lines = text.split('\n').length;
    if (lines > BRIEF_MAX_LINES) fail(file, `${lines} lines; a folder README is a brief (max ${BRIEF_MAX_LINES}) that links to docs/`);
    if (!/docs\//.test(text)) fail(file, 'does not link to its fuller docs under docs/');
  }
}

// Every entry the index names must exist.
for (const m of docsIndex.matchAll(/`([a-z0-9/._-]+\.(?:md|html))`/g)) {
  const target = m[1].startsWith('docs/') ? m[1] : `docs/${m[1]}`;
  if (!existsSync(target) && !existsSync(m[1])) fail('docs/README.md', `lists ${m[1]}, which does not exist`);
}

function top(file) {
  return file.split('/')[1];
}
function statSafe(path) {
  try {
    return statSync(path).isDirectory();
  } catch {
    return false;
  }
}

if (problems.length) {
  console.error(`check-docs: ${problems.length} problem(s)\n` + problems.map((p) => `  ${p}`).join('\n'));
  process.exit(1);
}
console.log(`check-docs: ${files.filter((f) => f.endsWith('.md')).length} markdown files in place`);
