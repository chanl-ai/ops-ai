#!/usr/bin/env node
// Keeps commit messages short and free of working notes: a subject, then at most three body lines saying why the old
// behaviour was wrong and what was run to prove the fix. How the author got there belongs nowhere in the history.
// Usage: commit-message-check.mjs --commit <msg-file> | --self-test
import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';

const MAX_SUBJECT = 72;
const MAX_BODY_LINES = 3;
const MAX_BODY_CHARS = 320;
const TRAILER = /^[A-Z][A-Za-z-]+: \S/;
const NARRATION = [
  [/\b(I|I'm|I've|I'd|we|we're|we've|our|my|me|us)\b/, 'first person'],
  [/\b(turned out|turns out|it seems|seemed|noticed|realis|realiz|figured|tried|first attempt|on second thought)/i, 'narration'],
  [/\b(previously|used to|was broken|the bug (was|where)|the flake was|root cause was)\b/i, 'history (say the current constraint)'],
  [/\b(QA (red|green) at|review (said|asked)|as (the owner|the reviewer|[A-Z][a-z]+) (asked|said))\b/i, 'process talk'],
  [/\b(simply|just|obviously|of course|basically)\b/i, 'filler word'],
];

export function problems(message) {
  const lines = message.split('\n').filter((l) => !l.startsWith('#'));
  const subject = (lines[0] ?? '').trim();
  const out = [];
  if (subject.length > MAX_SUBJECT) out.push(`subject is ${subject.length} characters; keep it to ${MAX_SUBJECT}`);
  if (/^(Merge|Revert|fixup!|squash!)/.test(subject)) return out;
  const body = lines.slice(1).map((l) => l.trim()).filter((l) => l && !TRAILER.test(l));
  if (body.length > MAX_BODY_LINES) out.push(`body has ${body.length} lines; keep it to ${MAX_BODY_LINES}: why the old behaviour was wrong, and what ran to prove the fix`);
  const chars = body.join(' ').length;
  if (chars > MAX_BODY_CHARS) out.push(`body has ${chars} characters; keep it under ${MAX_BODY_CHARS}`);
  for (const [re, what] of NARRATION) {
    const hit = [subject, ...body].map((l) => l.match(re)).find(Boolean);
    if (hit) out.push(`${what}: "${hit[0]}"`);
  }
  return out;
}

const SERVICE_SCOPES = new Set(['agents', 'tools', 'kb', 'platform', 'files', 'documents', 'models', 'runner']);

// A scope that names a service or package must match a changed path: a commit under another builder's message
// (a shared scratch folder, the wrong message file) shows up as a scope with nothing under it.
export function scopeProblems(message, paths, packageDirs = []) {
  const m = /^([a-z]+)\(([^)]*)\)!?:/.exec((message.split('\n').find((l) => !l.startsWith('#')) ?? '').trim());
  if (!m || !paths.length) return [];
  const type = m[1];
  const out = [];
  for (const scope of m[2].split(',').map((s) => s.trim()).filter(Boolean)) {
    const norm = scope.replace(/-/g, '_');
    let prefixes = null;
    if (SERVICE_SCOPES.has(scope)) prefixes = [`services/${scope}-service/`];
    else if (scope === 'store') prefixes = ['packages/ops_store/', 'deploy/database/', '/store/', '/migrations/'];
    else {
      const dir = packageDirs.find((d) => d === norm || d === `ops_${norm}`);
      if (dir) prefixes = [`packages/${dir}/`];
    }
    if (!prefixes) continue;
    // A path that carries the scope in its name (a doc, a fence list, a test file for it) is about it too; docs and
    // ci commits describe a service without living in it.
    const hit = type === 'docs' || type === 'ci' || paths.some((p) => p.includes(scope) || p.includes(norm) || prefixes.some((x) => (x.startsWith('/') ? `/${p}`.includes(x) : p.startsWith(x))));
    if (!hit) {
      out.push(`scope "${scope}" names ${prefixes[0]} but none of the changed paths (${paths.slice(0, 4).join(', ')}${paths.length > 4 ? ', ...' : ''}) is under it; is this the right message file?`);
    }
  }
  return out;
}

function packageDirs() {
  try { return readdirSync('packages'); } catch { return []; }
}

function stagedPaths() {
  try {
    return execFileSync('git', ['diff', '--cached', '--name-only', 'HEAD'], { encoding: 'utf8' }).split('\n').filter(Boolean);
  } catch { return []; }
}

function selfTest() {
  const ok = 'fix(agents): plan tests use their own ids\n\nShared ids let planner estimates drift on a reused database.\nChecked: both plan files 5/5 on a fresh and a reused database.\n\nChangelog: plan-tests\n';
  const cases = [
    [ok, 0],
    ['fix(x): y\n\nI found the flake was the data, which turned out to be shared ids.\n', 3],
    ['fix(x): y\n\nl1\nl2\nl3\nl4\n', 1],
    ['fix(x): y\n\n' + 'a'.repeat(400) + '\n', 1],
    ['feat(console): what is new moves to a button and shows the version\n\nChangelog: whats-new\n', 0],
    ['fix(x): y\n\nPreviously the walk read the sidebar too early.\n', 1],
  ];
  let failed = 0;
  const pk = ['ops_store', 'ops_service_kit', 'contracts'];
  const scopeCases = [
    ['fix(platform): x\n', ['services/agents-service/src/chat_connectors.py'], 1],
    ['fix(platform): x\n', ['services/platform-service/src/a.py'], 0],
    ['fix(store): x\n', ['services/kb-service/src/kb/store/repo.py'], 0],
    ['fix(store): x\n', ['services/kb-service/src/kb/api.py'], 1],
    ['fix(service-kit): x\n', ['docs/a.md'], 1],
    ['fix(docs): x\n', ['services/kb-service/a.py'], 0],
  ];
  for (const [msg, paths, want] of scopeCases) {
    if (scopeProblems(msg, paths, pk).length !== want) { failed++; console.log(`FAIL scope ${JSON.stringify(msg)} ${paths}`); }
  }
  for (const [msg, want] of cases) {
    const got = problems(msg).length;
    if ((want === 0) !== (got === 0) || (want > 0 && got < want)) {
      failed++;
      console.log(`FAIL want ${want} got ${got}: ${JSON.stringify(msg.slice(0, 60))} -> ${problems(msg).join('; ')}`);
    }
  }
  console.log(failed ? `${failed} failed` : `${cases.length} passed`);
  process.exit(failed ? 1 : 0);
}

const [flag, file] = process.argv.slice(2);
if (flag === '--self-test') selfTest();
else if (flag === '--commit' && file) {
  const text = readFileSync(file, 'utf8');
  const found = [...problems(text), ...scopeProblems(text, stagedPaths(), packageDirs())];
  if (found.length) {
    console.error('commit message refused (scripts/commit-message-check.mjs):');
    for (const p of found) console.error(`  - ${p}`);
    console.error('Write the subject, then at most three lines: why the old behaviour was wrong, and what ran to prove the fix.');
    process.exit(1);
  }
}
