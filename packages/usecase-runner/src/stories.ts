// A use case is told as a few user stories ("A team admin connects Salesforce and runs Test connection"), each on one
// layer, made of steps from the doc's steps table, and proved by one of them. A script's checks are named by the step
// they belong to ("3 the module is published"), so a run's checks map back onto the stories, and a run reports first
// which stories work and, for each broken one, the step that failed. The checks stay the evidence underneath.
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { isLayer, type Layer } from './layers.ts';
import type { UseCase } from './registry.ts';
import type { Checks } from './report.ts';
import { USECASE_DIR } from './resolve.ts';

export interface Story {
  id: string;
  text: string;
  layer: Layer;
  steps: number[];
  proof: number;
}

export class StoryError extends Error {}

const HEADER = ['#', 'story', 'layer', 'steps', 'proved by'];

function cells(line: string): string[] {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
}

/** "1-3, 5" as [1, 2, 3, 5]. */
function stepList(cell: string, where: string): number[] {
  const out: number[] = [];
  for (const part of cell.split(',').map((p) => p.trim()).filter(Boolean)) {
    const m = /^(\d+)(?:\s*-\s*(\d+))?$/.exec(part);
    if (!m) throw new StoryError(`${where}: steps must look like 1-3, 5; got "${cell}"`);
    const from = Number(m[1]);
    const to = m[2] === undefined ? from : Number(m[2]);
    if (to < from) throw new StoryError(`${where}: steps ${part} run backwards`);
    for (let n = from; n <= to; n++) out.push(n);
  }
  if (!out.length) throw new StoryError(`${where}: no steps`);
  return out;
}

/** The table under `## Stories` (columns # | Story | Layer | Steps | Proved by); none when the doc has no such section. */
export function parseStories(markdown: string, where = 'doc'): Story[] {
  const lines = markdown.split('\n');
  const section = lines.findIndex((l) => /^##\s+Stories\s*$/.test(l));
  if (section < 0) return [];
  const header = lines.findIndex((l, i) => i > section && l.trim().startsWith('|'));
  if (header < 0 || cells(lines[header]!).map((c) => c.toLowerCase()).join() !== HEADER.join()) {
    throw new StoryError(`${where}: the Stories table needs the columns # | Story | Layer | Steps | Proved by`);
  }
  const out: Story[] = [];
  for (const line of lines.slice(header + 2)) {
    if (!line.trim().startsWith('|')) break;
    const [id = '', text = '', layer = '', steps = '', proof = ''] = cells(line);
    const at = `${where} story ${id || '?'}`;
    if (!/^S\d+$/.test(id)) throw new StoryError(`${at}: the id must look like S1`);
    if (!text) throw new StoryError(`${at}: no story`);
    if (!isLayer(layer)) throw new StoryError(`${at}: layer must be api, sdk, cli or ui; got "${layer}"`);
    const list = stepList(steps, at);
    const proofStep = Number(proof);
    if (!/^\d+$/.test(proof) || !list.includes(proofStep)) throw new StoryError(`${at}: proved by must be one of its steps; got "${proof}"`);
    out.push({ id, text, layer, steps: list, proof: proofStep });
  }
  return out;
}

/** The use case's doc: the markdown file in its service folder whose Id line names it. */
export function findDoc(root: string, uc: UseCase): string | undefined {
  const dir = join(root, USECASE_DIR, uc.service);
  if (!existsSync(dir)) return undefined;
  const mark = new RegExp(`Id: \`${uc.id}\``);
  for (const name of readdirSync(dir).filter((n) => n.endsWith('.md')).sort()) {
    const path = join(USECASE_DIR, uc.service, name);
    if (mark.test(readFileSync(join(root, path), 'utf8'))) return path;
  }
  return undefined;
}

export function storiesOf(root: string, uc: UseCase): { doc?: string; stories: Story[] } {
  const doc = findDoc(root, uc);
  return doc ? { doc, stories: parseStories(readFileSync(join(root, doc), 'utf8'), doc) } : { stories: [] };
}

/** The step a check belongs to, from the number its name starts with; none for a check such as "no page errors". */
export function stepOf(check: string): number | undefined {
  const m = /^(\d+)\b/.exec(check);
  return m ? Number(m[1]) : undefined;
}

export type StoryState = 'works' | 'broken' | 'not run';

export interface StoryResult {
  story: Story;
  state: StoryState;
  why: string;
}

/**
 * What one layer's run says about each of its stories. A story works only when its proving step has a passing check
 * and none of its steps has a failing one; a script that stopped before the proving step leaves the story broken at
 * that step, never working by default.
 */
export function judge(stories: Story[], checks: Checks): StoryResult[] {
  return stories.map((story) => {
    const failed = checks.failed.find((c) => story.steps.includes(stepOf(c) ?? -1));
    if (failed) return { story, state: 'broken', why: `step ${stepOf(failed)} failed: ${failed}` };
    const proved = checks.passed.some((c) => stepOf(c) === story.proof);
    if (!proved) return { story, state: 'broken', why: `the script stopped before step ${story.proof}` };
    return { story, state: 'works', why: '' };
  });
}

/** Checks no story claims, so a failure outside the stories is still shown. */
export function unclaimed(stories: Story[], checks: Checks): Checks {
  const claimed = (c: string) => stories.some((s) => s.steps.includes(stepOf(c) ?? -1));
  return { passed: checks.passed.filter((c) => !claimed(c)), failed: checks.failed.filter((c) => !claimed(c)) };
}

/** One saved run of one use case on one layer, so `report` can answer without running anything. */
export interface SavedRun {
  id: string;
  layer: Layer;
  at: string;
  exit: number | null;
  checks: Checks;
}

export const RUNS_DIR = '.run/usecases';

export function saveRun(root: string, run: SavedRun): void {
  const dir = join(root, RUNS_DIR);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${run.id}-${run.layer}.json`), `${JSON.stringify(run, null, 2)}\n`);
}

export function loadRun(root: string, id: string, layer: Layer): SavedRun | undefined {
  const path = join(root, RUNS_DIR, `${id}-${layer}.json`);
  return existsSync(path) ? (JSON.parse(readFileSync(path, 'utf8')) as SavedRun) : undefined;
}

/** The stories block for one use case: one line per story, then any check outside the stories that failed. */
export function formatStories(uc: UseCase, stories: Story[], runs: Partial<Record<Layer, SavedRun>>): string {
  if (!stories.length) return `${uc.id} ${uc.title}\n  no stories yet: add a Stories table to its doc (make usecase-new writes one)`;
  const lines = [`${uc.id} ${uc.title}`];
  const extra: string[] = [];
  for (const layer of [...new Set(stories.map((s) => s.layer))]) {
    const mine = stories.filter((s) => s.layer === layer);
    const run = runs[layer];
    const results: StoryResult[] = run ? judge(mine, run.checks) : mine.map((story) => ({ story, state: 'not run', why: `run make usecase-test UC=${uc.id} LAYER=${layer}` }));
    for (const r of results) {
      lines.push(`  ${r.state.padEnd(7)} ${r.story.id.padEnd(3)} ${layer.padEnd(3)}  ${r.story.text}${r.why ? `\n                       ${r.why}` : ''}`);
    }
    if (run) {
      const rest = unclaimed(mine, run.checks);
      for (const f of rest.failed) extra.push(`  also failed (${layer}): ${f}`);
      const total = run.checks.passed.length + run.checks.failed.length;
      extra.push(`  ${layer} checks inside: ${run.checks.passed.length} of ${total} passed${run.exit === 0 ? '' : `, script exited ${run.exit ?? 'by signal'}`} (${run.at})`);
    }
  }
  return [...lines, ...extra].join('\n');
}
