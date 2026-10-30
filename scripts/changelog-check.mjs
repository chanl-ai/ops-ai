#!/usr/bin/env node
// The changelog the console shows under What's new (changelog/<topic>.json, one entry per file, its date inside) and the roadmap
// under Coming next (roadmap.json), and the gate that keeps them current (c-510).
//
//   --entries                 every entry and roadmap item is written for a person using the console (make verify)
//   --commit <msgfile>        the commit-msg hook: a feat or fix that changes apps/ or services/ names its card in a
//                             Card: or Feature: trailer, and the changelog as staged has an entry for that card
//   --shas <sha>...           the same rule over these commits, read against the changelog of the last one (repo.sh card)
//   --range <a>..<b>          the same over a range, merges skipped, against the changelog at <b> (repo.sh snapshot)
//   --repo <dir>              the repository to read (default: this one)
//   --self-test               the rules' own red and green cases, and the hook on a scratch repository
//
// Entries are written by people, never derived from commits: commit subjects are for reviewers and name internals.
import { execFileSync, spawnSync } from 'node:child_process';
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(name);
  return i < 0 ? null : args[i + 1];
};
const repo = opt('--repo') ?? join(HERE, '..');
const git = (argv, cwd = repo) => execFileSync('git', argv, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
const tryGit = (argv, cwd = repo) => {
  try {
    return git(argv, cwd);
  } catch {
    return null;
  }
};

// ---------------------------------------------------------------------------------------------------------------------
// Wording: what a person using the console reads. Refused are internals and narration, nothing else, so honest words
// ("10,000,000 rows", "used to sign in", "contact us") pass.

const TAGS = new Set(['new', 'improved', 'fix']);
// The console's release switches (apps/console/src/lib/changelog.ts SWITCHES): an entry for a feature behind one names
// it, and What's new shows the entry only while it is on. A name the console does not read would hide the entry for good.
const SWITCHES = new Set([
  'NEXT_PUBLIC_OPS_PLUGINS',
  'NEXT_PUBLIC_OPS_PERSONAL_SIGNIN',
  'NEXT_PUBLIC_OPS_REAL_CONNECTIONS',
  'NEXT_PUBLIC_OPS_DOCUMENT_READS',
  'NEXT_PUBLIC_OPS_HOSTED_FORMS',
  'NEXT_PUBLIC_OPS_WORKFLOW_BUILDER',
]);
const REFUSED = [
  [/(^|\s)(apps|services|packages|src|docs|scripts)\/\S*/i, 'names a file path'],
  [/\S+\/\S*\.[a-z]{1,5}\b/i, 'names a file path'],
  [/\b[\w-]+\.(tsx?|jsx?|mjs|py|json|md|sql|ya?ml|sh|css|toml)\b/i, 'names a file'],
  [/\b(?:c|uc)-\d+\b/i, 'names a card or use case id'],
  [/\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b/, 'names a commit hash'],
  [/\b(I|we|We|my|My|our|Our)\b/, 'speaks in the first person'],
  [/\b(turned out|it turns out|the bug where|previously|was broken|we found|I found|root cause)\b/i, 'narrates the debugging'],
];
const sentences = (text) => (text.trim().match(/[^.!?]+[.!?]+(\s|$)/g) ?? []).length;
const endsAsSentence = (text) => /[.!?]$/.test(text.trim());

function wordingProblems(texts) {
  const out = [];
  for (const [field, text] of texts) for (const [re, why] of REFUSED) if (re.test(text)) out.push(`${field} ${why}`);
  return out;
}

/** What is wrong with one changelog entry, as `rule` strings; empty when it is fine. */
export function entryProblems(entry) {
  const out = [];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(entry?.date ?? '')) out.push('date is not YYYY-MM-DD');
  if (!TAGS.has(entry?.tag)) out.push('tag is not new, improved or fix');
  const title = String(entry?.title ?? '');
  const description = String(entry?.description ?? '');
  if (!title.trim() || title.length > 60) out.push('title is not 1 to 60 characters');
  const n = sentences(description);
  if (!endsAsSentence(description) || n < 1 || n > 2) out.push('description is not one or two sentences');
  if (!Array.isArray(entry?.cards) || entry.cards.length === 0) out.push('cards names no card');
  if (entry?.switch !== undefined && !SWITCHES.has(entry.switch)) out.push(`switch is not one the console reads: ${[...SWITCHES].join(', ')}`);
  return [...out, ...wordingProblems([['title', title], ['description', description]])];
}

/** What is wrong with one Coming next item. */
export function roadmapProblems(item) {
  const out = [];
  const title = String(item?.title ?? '');
  const line = String(item?.line ?? '');
  if (!title.trim() || title.length > 60) out.push('title is not 1 to 60 characters');
  if (!endsAsSentence(line) || sentences(line) !== 1) out.push('line is not one sentence');
  return [...out, ...wordingProblems([['title', title], ['line', line]])];
}

// ---------------------------------------------------------------------------------------------------------------------
// Reading the changelog from the working tree, the index (':') or a commit.

function readChangelog(ref) {
  const entries = [];
  if (ref === null) {
    const dir = join(repo, 'changelog');
    for (const f of existsSync(dir) ? readdirSync(dir).filter((x) => x.endsWith('.json')).sort() : []) entries.push([f, readFileSync(join(dir, f), 'utf8')]);
  } else {
    const listing = ref === ':' ? tryGit(['ls-files', '--', 'changelog/']) : tryGit(['ls-tree', '-r', '--name-only', ref, '--', 'changelog/']);
    for (const p of (listing ?? '').split('\n').filter((x) => x.endsWith('.json')))
      entries.push([p.slice('changelog/'.length), git(['show', ref === ':' ? `:${p}` : `${ref}:${p}`])]);
  }
  return entries.map(([id, text]) => {
    try {
      return { id, entry: JSON.parse(text) };
    } catch {
      return { id, entry: null };
    }
  });
}

function readRoadmap() {
  const p = join(repo, 'roadmap.json');
  return existsSync(p) ? JSON.parse(readFileSync(p, 'utf8')) : [];
}

function checkEntries() {
  const bad = [];
  for (const { id, entry } of readChangelog(null)) {
    if (!entry) bad.push(`changelog/${id}: not valid JSON`);
    else for (const p of entryProblems(entry)) bad.push(`changelog/${id}: ${p}`);
    if (!/^[a-z0-9-]+\.json$/.test(id)) bad.push(`changelog/${id}: name is not <topic>.json in lower case`);
  }
  readRoadmap().forEach((item, i) => roadmapProblems(item).forEach((p) => bad.push(`roadmap.json item ${i + 1}: ${p}`)));
  return bad;
}

// ---------------------------------------------------------------------------------------------------------------------
// The gate.

const NEEDS_ENTRY = /^(feat|fix)(\([^)]*\))?!?:/;
const USER_PATHS = /^(apps|services)\//;
const trailerIds = (message) => [...message.matchAll(/^(?:Card|Feature):\s*([A-Za-z]{1,10}-\d{1,6})\s*$/gm)].map((m) => m[1]);
const subjectOf = (message) => message.split('\n').find((l) => l.trim() && !l.startsWith('#')) ?? '';

/** The commit that added the hook: commits before it, and cards that already had them, are not gated. */
function gateStart() {
  const out = tryGit(['log', '--diff-filter=A', '--format=%H', '--', '.githooks/commit-msg']);
  return out?.trim().split('\n').filter(Boolean).at(-1) ?? null;
}
function cardBeforeGate(id, start) {
  const range = start ? [`${start}^`] : ['HEAD'];
  const hit = tryGit(['log', '-1', '--format=%H', '-E', `--grep=^(Card|Feature): ${id}$`, ...range]);
  return !!hit?.trim();
}
const cardsWithEntries = (ref) => new Set(readChangelog(ref).flatMap(({ entry }) => (Array.isArray(entry?.cards) ? entry.cards : [])));

const howToAdd = (id) =>
  `add changelog/<topic>.json with {"date","title","description","tag":"new|improved|fix","cards":["${id}"]}, written for a person using the console, and stage it`;

function checkCommit(msgFile) {
  const message = readFileSync(msgFile, 'utf8');
  const gitDir = git(['rev-parse', '--git-dir']).trim();
  if (existsSync(join(repo, gitDir, 'MERGE_HEAD'))) return [];
  if (!NEEDS_ENTRY.test(subjectOf(message))) return [];
  const staged = git(['diff', '--cached', '--name-only']).split('\n').filter(Boolean);
  if (!staged.some((p) => USER_PATHS.test(p))) return [];
  const ids = trailerIds(message);
  if (!ids.length) return ['a feat or fix that changes apps/ or services/ names its card: add a Card: c-N trailer'];
  const has = cardsWithEntries(':');
  const start = gateStart();
  const bad = [];
  for (const id of ids) {
    if (has.has(id)) continue;
    if (cardBeforeGate(id, start)) {
      console.error(`changelog: ${id} was in progress before the gate, so this commit passes; ${howToAdd(id)} before the card is published`);
      continue;
    }
    bad.push(`${id} has no changelog entry: ${howToAdd(id)}`);
  }
  // Staged entries are checked as they will be published.
  for (const { id, entry } of readChangelog(':')) for (const p of entry ? entryProblems(entry) : ['not valid JSON']) bad.push(`changelog/${id}: ${p}`);
  return bad;
}

/** Commits that owe no entry because nothing they did reaches a person (changelog-exempt.json at `ref`): each row
 * names a commit by at least 7 characters of its sha and the reason, which a reviewer reads in the diff that adds it.
 * Rows without a reason are ignored. */
function readExempt(ref) {
  const text = tryGit(['show', `${ref}:changelog-exempt.json`]);
  if (!text) return [];
  try {
    const rows = JSON.parse(text);
    return Array.isArray(rows) ? rows.filter((r) => String(r?.commit ?? '').length >= 7 && String(r?.reason ?? '').trim()) : [];
  } catch {
    return [];
  }
}

/** The rule over commits already made, read against the changelog at `at`. */
function checkShas(shas, at) {
  const start = gateStart();
  const has = cardsWithEntries(at);
  // A cardless commit is covered by an entry that names it in `commits`: its message cannot change once made.
  const covered = readChangelog(at).flatMap(({ entry }) => (Array.isArray(entry?.commits) ? entry.commits : []));
  const exempt = readExempt(at).map((r) => String(r.commit));
  const bad = [];
  for (const sha of shas) {
    if (exempt.some((c) => sha.startsWith(c))) continue;
    // Commits made before the gate landed are not held to it.
    if (start && tryGit(['merge-base', '--is-ancestor', start, sha]) === null) continue;
    const parents = git(['rev-list', '--parents', '-n', '1', sha]).trim().split(' ').length - 1;
    if (parents > 1) continue;
    const message = git(['show', '-s', '--format=%B', sha]);
    if (!NEEDS_ENTRY.test(subjectOf(message))) continue;
    const paths = git(['diff-tree', '--no-commit-id', '--name-only', '-r', sha]).split('\n').filter(Boolean);
    if (!paths.some((p) => USER_PATHS.test(p))) continue;
    // A change a later commit undid (a git revert, or the files put back by hand) never reaches anyone: every app or
    // service file it touched reads at `at` as it did before it (its card's notes may move on). A file changed again
    // since still counts, so its entry is still owed.
    if (tryGit(['diff', '--quiet', `${sha}^`, at, '--', ...paths.filter((p) => USER_PATHS.test(p))]) !== null) continue;
    const ids = trailerIds(message);
    if (!ids.length && !covered.some((c) => String(c).length >= 7 && sha.startsWith(String(c)))) bad.push(`${sha.slice(0, 8)} ${subjectOf(message)}: a feat or fix that changes apps/ or services/ names no card`);
    for (const id of ids) if (!has.has(id) && !cardBeforeGate(id, start)) bad.push(`${sha.slice(0, 8)}: ${id} has no changelog entry; ${howToAdd(id)}`);
  }
  for (const { id, entry } of readChangelog(at)) for (const p of entry ? entryProblems(entry) : ['not valid JSON']) bad.push(`changelog/${id}: ${p}`);
  return [...new Set(bad)];
}

// ---------------------------------------------------------------------------------------------------------------------
// Self-test.

function selfTest() {
  const results = [];
  const expect = (name, ok) => results.push([name, ok]);
  const clean = { date: '2026-10-22', title: 'Pages wait for your team', description: 'A record in another team says so and offers a switch.', tag: 'fix', cards: ['c-505'] };
  expect('a clean entry passes', entryProblems(clean).length === 0);
  const red = {
    'a file path': { description: 'The page in apps/console/src/app/page.tsx loads faster.' },
    'a bare path with an extension': { description: 'The layout in case-page.tsx loads faster.' },
    'a card id': { description: 'Built for c-505 so pages wait.' },
    'a commit hash': { description: 'Since 23cad692 pages wait for your team.' },
    'first person': { description: 'We made pages wait for your team.' },
    'debugging narration': { description: 'It turned out pages loaded too early.' },
    'a 61-character title': { title: 'x'.repeat(61) },
    'three sentences': { description: 'One. Two. Three.' },
    'no full stop': { description: 'Pages wait for your team' },
    'a switch the console does not know': { switch: 'NEXT_PUBLIC_OPS_PLUGINZ' },
  };
  for (const [what, change] of Object.entries(red)) expect(`refused: ${what}`, entryProblems({ ...clean, ...change }).length > 0);
  const green = ['Imports 10,000,000 rows.', 'People who used to sign in with a password keep their access.', 'If it fails, contact us.', 'Search shows what it found.', 'A form can be used to start a case.'];
  for (const d of green) expect(`passes: "${d}"`, entryProblems({ ...clean, description: d }).length === 0);
  expect('passes: an entry behind a release switch', entryProblems({ ...clean, switch: 'NEXT_PUBLIC_OPS_PLUGINS' }).length === 0);
  expect('a roadmap item passes', roadmapProblems({ title: 'Cases from chat', line: 'Start a case from any conversation.' }).length === 0);
  expect('refused: a roadmap line with a path', roadmapProblems({ title: 'Cases', line: 'Edits in services/agents-service land.' }).length > 0);

  // The hook on a scratch repository: codeloop's commit-msg hook still adds Feature:, and ours refuses or passes.
  const dir = mkdtempSync(join(tmpdir(), 'changelog-gate-'));
  const sh = (cmd, env = {}) => spawnSync('sh', ['-c', cmd], { cwd: dir, encoding: 'utf8', env: { ...process.env, ...env } });
  try {
    sh('git init -q -b feat/c-900-thing && git config user.email t@example.test && git config user.name t');
    mkdirSync(join(dir, '.githooks'));
    mkdirSync(join(dir, 'scripts'));
    cpSync(join(HERE, 'changelog-check.mjs'), join(dir, 'scripts/changelog-check.mjs'));
    cpSync(join(HERE, 'install-hooks.sh'), join(dir, 'scripts/install-hooks.sh'));
    // The commit-msg hook also runs the message check (commit-message-check.mjs); without it every commit is refused.
    cpSync(join(HERE, 'commit-message-check.mjs'), join(dir, 'scripts/commit-message-check.mjs'));
    cpSync(join(HERE, '../.githooks/commit-msg'), join(dir, '.githooks/commit-msg'));
    writeFileSync(join(dir, '.githooks/pre-commit'), '#!/bin/sh\nexit 0\n');
    // A card in progress before the gate lands.
    mkdirSync(join(dir, 'apps'));
    writeFileSync(join(dir, 'apps/a.ts'), '1\n');
    sh('git add apps && git commit -q -m "feat(x): older work" -m "Card: c-800"');
    // codeloop's hook, as `codeloop init --hooks` installs it.
    writeFileSync(join(dir, '.git/hooks/commit-msg'), readFileSync(join(HERE, 'tests/codeloop-commit-msg.sh'), 'utf8'));
    chmodSync(join(dir, '.git/hooks/commit-msg'), 0o755);
    sh('sh scripts/install-hooks.sh');
    expect("the installer keeps codeloop's hook", existsSync(join(dir, '.git/hooks/commit-msg.codeloop')));
    sh('git add .githooks scripts && git commit -q -m "chore: the changelog gate"');
    const commit = (subject, trailer = '') => {
      writeFileSync(join(dir, 'apps/a.ts'), `${Math.random()}\n`);
      sh('git add apps');
      return sh(`git commit -q -m "${subject}"${trailer ? ` -m "${trailer}"` : ''}`).status === 0;
    };
    expect('refused: feat with no entry (Feature: from the branch)', !commit('feat(x): a thing'));
    commit('docs(x): notes');
    expect("codeloop's hook still adds Feature:", sh('git log -1 --format=%B').stdout.includes('Feature: c-900'));
    sh('git checkout -q -b plain');
    expect('refused: feat with no trailer at all', !commit('feat(x): a thing'));
    expect('passes: docs with no entry', commit('docs(x): a note'));
    expect('passes with a warning: a card in progress before the gate', commit('fix(x): more', 'Card: c-800'));
    mkdirSync(join(dir, 'changelog'));
    writeFileSync(join(dir, 'changelog/a-thing.json'), JSON.stringify({ ...clean, cards: ['c-901'] }));
    sh('git add changelog');
    expect('passes: feat with its entry staged', commit('feat(x): a thing', 'Card: c-901'));
    writeFileSync(join(dir, 'changelog/b-thing.json'), JSON.stringify({ ...clean, description: 'We fixed it.', cards: ['c-902'] }));
    sh('git add changelog');
    expect('refused: feat whose staged entry is in the first person', !commit('feat(x): b thing', 'Card: c-902'));
    // repo.sh's check over commits already made: one that skipped the hook is refused, one with its entry passes.
    sh('git reset -q -- changelog/b-thing.json && rm changelog/b-thing.json');
    writeFileSync(join(dir, 'apps/a.ts'), 'skipped\n');
    sh('git add apps && git commit -q --no-verify -m "feat(x): skipped the hook" -m "Card: c-903"');
    const skipped = sh('git rev-parse HEAD').stdout.trim();
    const withEntry = sh('git log -1 --format=%H --grep="^Card: c-901$"').stdout.trim();
    const shas = (...s) => spawnSync('node', [join(dir, 'scripts/changelog-check.mjs'), '--repo', dir, '--shas', ...s], { encoding: 'utf8' }).status;
    expect('repo.sh check refuses a commit that skipped the hook', shas(skipped) === 1);
    expect('repo.sh check passes a commit with its entry', shas(withEntry) === 0);
    writeFileSync(join(dir, 'apps/a.ts'), 'cardless\n');
    sh('git add apps && git commit -q --no-verify -m "feat(x): cardless"');
    const cardless = sh('git rev-parse HEAD').stdout.trim();
    expect('repo.sh check refuses a cardless feat on apps/', shas(cardless) === 1);
    writeFileSync(join(dir, 'changelog/cardless.json'), JSON.stringify({ ...clean, cards: ['c-906'], commits: [cardless.slice(0, 8)] }));
    sh('git add changelog && git commit -q --no-verify -m "chore: cover cardless"');
    expect('repo.sh check passes a cardless feat once its sha is listed in commits', shas(cardless, sh('git rev-parse HEAD').stdout.trim()) === 0);
    // A feat a later commit took back, file for file, owes no entry; one changed again afterwards still does.
    writeFileSync(join(dir, 'apps/mock.ts'), 'a mock\n');
    sh('git add apps && git commit -q --no-verify -m "feat(x): a mock page" -m "Card: c-904"');
    const mock = sh('git rev-parse HEAD').stdout.trim();
    sh('git rm -q apps/mock.ts && git commit -q --no-verify -m "revert(x): drop the mock" -m "Card: c-904"');
    expect('repo.sh check passes a feat a later commit undid', shas(mock, sh('git rev-parse HEAD').stdout.trim()) === 0);
    writeFileSync(join(dir, 'apps/kept.ts'), 'first\n');
    sh('git add apps && git commit -q --no-verify -m "feat(x): kept" -m "Card: c-905"');
    const kept = sh('git rev-parse HEAD').stdout.trim();
    writeFileSync(join(dir, 'apps/kept.ts'), 'second\n');
    sh('git add apps && git commit -q --no-verify -m "docs(x): touch kept" -m "Card: c-905"');
    expect('repo.sh check refuses a feat whose files moved on, not back', shas(kept, sh('git rev-parse HEAD').stdout.trim()) === 1);
    // A listed commit with a reason owes no entry; a row with no reason excuses nothing.
    writeFileSync(join(dir, 'changelog-exempt.json'), JSON.stringify([{ commit: kept.slice(0, 8) }]));
    sh('git add changelog-exempt.json && git commit -q --no-verify -m "chore: exempt without a reason"');
    expect('repo.sh check refuses a commit listed without a reason', shas(kept, sh('git rev-parse HEAD').stdout.trim()) === 1);
    writeFileSync(join(dir, 'changelog-exempt.json'), JSON.stringify([{ commit: kept.slice(0, 8), reason: 'a mock page, deleted' }]));
    sh('git add changelog-exempt.json && git commit -q --no-verify -m "chore: exempt with a reason"');
    expect('repo.sh check passes a commit listed with a reason', shas(kept, sh('git rev-parse HEAD').stdout.trim()) === 0);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
  for (const [name, ok] of results) console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
  return results.every(([, ok]) => ok);
}

// ---------------------------------------------------------------------------------------------------------------------

const fail = (lines, what) => {
  if (!lines.length) return 0;
  console.error(`changelog: ${what}\n${lines.map((l) => `  ${l}`).join('\n')}`);
  return 1;
};
let code = 0;
if (args.includes('--self-test')) code = selfTest() ? 0 : 1;
else if (args.includes('--entries')) code = fail(checkEntries(), 'entries are written for a person using the console');
else if (opt('--commit')) code = fail(checkCommit(opt('--commit')), 'this commit needs a changelog entry');
else if (args.includes('--shas')) {
  const shas = args.slice(args.indexOf('--shas') + 1).filter((a) => !a.startsWith('--') && a !== opt('--repo'));
  code = fail(checkShas(shas, shas.at(-1)), 'these commits need changelog entries');
} else if (opt('--range')) {
  const [, b] = opt('--range').split('..');
  const shas = git(['rev-list', '--reverse', '--no-merges', opt('--range')]).split('\n').filter(Boolean);
  code = fail(checkShas(shas, b), 'this range needs changelog entries');
} else {
  console.error('usage: changelog-check.mjs --entries | --commit <msgfile> | --shas <sha>... | --range <a>..<b> | --self-test [--repo <dir>]');
  code = 2;
}
process.exit(code);
