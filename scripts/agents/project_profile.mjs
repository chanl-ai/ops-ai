// Reads the project profile (.claude/project-profile.md, or the file OPS_AGENT_PROFILE names) for the Node agent
// scripts: every markdown table, keyed by the heading above it, with cells read by column name. The Python twin is
// project_profile.py; both parse the same file so a fact lives once.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';

export const PROFILE_PATH = '.claude/project-profile.md';
const SEPARATOR = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

/** The repository root: git's answer, else the first parent holding the profile, else the current folder. */
export function findRoot(start = process.cwd()) {
  try {
    const out = execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: start, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    if (out) return out;
  } catch {
    // not a git checkout; fall through
  }
  let dir = resolve(start);
  for (;;) {
    if (existsSync(join(dir, PROFILE_PATH))) return dir;
    const up = dirname(dir);
    if (up === dir) return resolve(start);
    dir = up;
  }
}

/** A cell's text without the backticks that mark code. */
export const plain = (cell) => (cell ?? '').replaceAll('`', '').trim();

function cells(line) {
  let body = line.trim();
  if (body.startsWith('|')) body = body.slice(1);
  if (body.endsWith('|') && !body.endsWith('\\|')) body = body.slice(0, -1);
  return body.split(/(?<!\\)\|/).map((c) => c.replaceAll('\\|', '|').trim());
}

/** Every markdown table in `text`, keyed by the nearest heading above it. */
export function parseProfile(text) {
  const sections = {};
  let section = '';
  const lines = text.split('\n');
  for (let i = 0; i < lines.length; ) {
    const line = lines[i];
    if (line.startsWith('#')) {
      section = line.replace(/^#+/, '').trim();
      i += 1;
      continue;
    }
    if (line.trimStart().startsWith('|') && i + 1 < lines.length && SEPARATOR.test(lines[i + 1].trim())) {
      const header = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trimStart().startsWith('|')) {
        const values = cells(lines[i]);
        rows.push(Object.fromEntries(header.map((h, j) => [h, values[j] ?? ''])));
        i += 1;
      }
      (sections[section] ??= []).push(rows);
      continue;
    }
    i += 1;
  }
  return sections;
}

/** The profile at `path`, else OPS_AGENT_PROFILE, else the repository's own; with `root`, `tables`, `table`, `value`. */
export function loadProfile(path, root = findRoot()) {
  let chosen = path ?? process.env.OPS_AGENT_PROFILE ?? join(root, PROFILE_PATH);
  if (!isAbsolute(chosen)) chosen = join(root, chosen);
  if (!existsSync(chosen)) throw new Error(`no project profile at ${chosen}; write one (see .claude/project-profile.md) or set OPS_AGENT_PROFILE`);
  const sections = parseProfile(readFileSync(chosen, 'utf8'));
  const tables = (section) => {
    const key = Object.keys(sections).find((k) => k.toLowerCase() === section.toLowerCase());
    if (!key) throw new Error(`profile ${chosen} has no section "${section}"; it has ${Object.keys(sections).join(', ')}`);
    return sections[key];
  };
  const table = (section, column) => {
    const all = tables(section);
    if (!column) return all[0] ?? [];
    const found = all.find((rows) => rows[0] && column in rows[0]);
    if (!found) throw new Error(`profile section "${section}" has no table with a column "${column}"`);
    return found;
  };
  const value = (section, key, keyColumn = 'Setting', valueColumn = 'Value') => {
    const row = table(section, keyColumn).find((r) => plain(r[keyColumn]).toLowerCase() === key.toLowerCase());
    if (!row) throw new Error(`profile section "${section}" has no row "${key}"`);
    return plain(row[valueColumn]);
  };
  return { path: chosen, root, sections, tables, table, value };
}
