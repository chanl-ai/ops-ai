#!/usr/bin/env node
// Limits a QA fix: a commit whose subject starts `fix(qa):` may change test and use case files, seed and fixture files
// freely, and at most 20 lines (added plus removed) in other source files, each of which the card's plan names.
// Anything larger is a filed bug for a builder, so QA cannot grow into a second builder.
// The plan's files come from the QA_PLAN_FILES variable (space or comma separated; a trailing / names a folder) or, when
// it is unset, from the file `qa-plan-files` in the git directory. With neither, no source line is allowed.
// Usage: qa-fix-check.mjs --commit <msg-file> | --self-test
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

export const MAX_SOURCE_LINES = 20;
const SUBJECT = /^fix\(qa\):/;
const FREE = [
  /(^|\/)tests?\//,
  /(^|\/)test_[^/]*\.py$/,
  /\.(test|spec)\.[cm]?[jt]sx?$/,
  /^docs\/usecases\//,
  /(^|\/)(seed|fixtures?)\//,
];

export const isFree = (path) => FREE.some((re) => re.test(path));

export function problems(subject, changes, planFiles) {
  if (!SUBJECT.test(subject)) return [];
  const out = [];
  let lines = 0;
  for (const { path, lines: n } of changes) {
    if (isFree(path)) continue;
    lines += n;
    const named = planFiles.some((p) => (p.endsWith('/') ? path.startsWith(p) : path === p));
    if (!named) out.push(`${path} is not a test, use case, seed or fixture file and the plan does not name it`);
  }
  if (lines > MAX_SOURCE_LINES) out.push(`${lines} changed source lines; a fix(qa) commit allows ${MAX_SOURCE_LINES}, file a bug for the rest`);
  return out;
}

function stagedChanges(cwd) {
  const raw = execFileSync('git', ['diff', '--cached', '--numstat', '--no-renames'], { cwd, encoding: 'utf8' });
  return raw.split('\n').filter(Boolean).map((l) => {
    const [a, d, ...p] = l.split('\t');
    // Binary files report "-": count them as over the limit so they never pass as small.
    const n = a === '-' ? MAX_SOURCE_LINES + 1 : Number(a) + Number(d);
    return { path: p.join('\t'), lines: n };
  });
}

function planFiles(cwd) {
  if (process.env.QA_PLAN_FILES !== undefined) return process.env.QA_PLAN_FILES.split(/[\s,]+/).filter(Boolean);
  const dir = execFileSync('git', ['rev-parse', '--absolute-git-dir'], { cwd, encoding: 'utf8' }).trim();
  const file = join(dir, 'qa-plan-files');
  return existsSync(file) ? readFileSync(file, 'utf8').split(/[\s,]+/).filter(Boolean) : [];
}

const [flag, file] = process.argv.slice(2);
if (flag === '--commit' && file) {
  const subject = (readFileSync(file, 'utf8').split('\n')[0] ?? '').trim();
  if (SUBJECT.test(subject)) {
    const cwd = process.cwd();
    const found = problems(subject, stagedChanges(cwd), planFiles(cwd));
    if (found.length) {
      console.error(`fix(qa) commit refused (scripts/qa-fix-check.mjs): ${found.join('; ')}`);
      process.exit(1);
    }
  }
}
