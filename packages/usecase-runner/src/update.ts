// `update <id>`: where the doc and scripts are, and which steps changed since each layer's last green run. A green run
// records the commit it started from; the doc at that commit is compared with the doc now, step by step.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { LAYERS } from './layers.ts';
import type { UseCase } from './registry.ts';
import { resolveScript } from './resolve.ts';
import { findDoc, loadGreen, parseSteps, type Step } from './stories.ts';

function git(root: string, args: string[]): string | undefined {
  try {
    return execFileSync('git', ['-C', root, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  } catch {
    return undefined;
  }
}

/** Steps added, removed or reworded between two versions of a doc. */
export function changedSteps(before: Step[], after: Step[]): string[] {
  const old = new Map(before.map((s) => [s.n, s]));
  const out: string[] = [];
  for (const s of after) {
    const o = old.get(s.n);
    if (!o) out.push(`step ${s.n} is new: ${s.step}`);
    else if (o.step !== s.step || o.expected !== s.expected) out.push(`step ${s.n} changed: ${s.step}`);
    old.delete(s.n);
  }
  for (const s of old.values()) out.push(`step ${s.n} was removed: ${s.step}`);
  return out;
}

export function updateReport(root: string, uc: UseCase): string {
  const doc = findDoc(root, uc);
  if (!doc) return `${uc.id} ${uc.title}\n  no doc names this id; check docs/usecases/${uc.service}/`;
  const now = parseSteps(readFileSync(join(root, doc), 'utf8'));
  const lines = [`${uc.id} ${uc.title}`, `  doc     ${doc}`];
  for (const l of LAYERS) {
    const r = resolveScript(root, uc, l);
    if (r.kind === 'script') lines.push(`  ${l.padEnd(7)} ${r.path}`);
  }
  const greens = LAYERS.flatMap((l) => {
    const g = loadGreen(root, uc.id, l);
    return g ? [g] : [];
  });
  if (!greens.length) {
    lines.push('  no green run is recorded here, so every step counts as changed:');
    lines.push(...now.map((s) => `    step ${s.n}: ${s.step}`));
    return lines.join('\n');
  }
  for (const g of greens) {
    const where = `${g.layer}, green ${g.at.slice(0, 16).replace('T', ' ')}`;
    const old = g.commit ? git(root, ['show', `${g.commit}:${doc}`]) : undefined;
    if (old === undefined) {
      lines.push(`  since ${where}: cannot compare, the commit is not in this clone`);
      continue;
    }
    const steps = changedSteps(parseSteps(old), now);
    const script = resolveScript(root, uc, g.layer);
    const scriptChanged = script.kind === 'script' && Boolean(git(root, ['diff', '--stat', g.commit!, '--', script.path])?.trim());
    lines.push(`  since ${where}:`);
    lines.push(...(steps.length ? steps.map((s) => `    ${s}`) : ['    no step changed']));
    if (scriptChanged) lines.push('    the script changed');
  }
  return lines.join('\n');
}
