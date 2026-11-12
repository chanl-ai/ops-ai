// A use case page (docs/usecases/<area>/<topic>.md, format in docs/usecases/use-case-areas.md) is its own test: the
// code tabs under "Before you start" and each numbered step run in order, one program per tab, against a stack the run
// starts. Each step prints `PASS <tab> step <n>: <title> (<page>:<line>)` or a FAIL naming the page line, so the
// runner's PASS/FAIL contract (report.ts) holds for pages as it does for scripts.
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { Layer } from './layers.ts';
import { DB_VAR, dropDatabase, runDatabaseName } from './isolation.ts';
import { commandFor, runScript } from './run.ts';

export const TABS = ['Python', 'TypeScript', 'CLI', 'MCP'] as const;
export type Tab = (typeof TABS)[number];

/** The tabs a layer runs: the two SDKs for `sdk`, the command line for `cli`, an MCP client (Python, as Claude or Cursor connects) for `mcp`. */
export const LAYER_TABS: Partial<Record<Layer, Tab[]>> = { sdk: ['Python', 'TypeScript'], cli: ['CLI'], mcp: ['MCP'] };

export interface Block {
  tab: Tab;
  code: string;
  /** Page line (1-based) of the block's first code line. */
  line: number;
}

export interface PageStep {
  n: number;
  title: string;
  line: number;
  blocks: Block[];
}

export interface Page {
  path: string;
  setup: Block[];
  steps: PageStep[];
  /** Saved sign-in profiles the page's people use, from "Who is in it". */
  profiles: string[];
  /** Open rows of the Gaps table; a page with one does not pass. */
  gaps: { line: number; text: string }[];
  /** The "Services the run starts" row of Details, as written. */
  services: string;
}

const FENCE = /^```\w*.*\btab="([^"]+)"/;

export function parsePage(text: string, path: string): Page {
  const lines = text.split('\n');
  const page: Page = { path, setup: [], steps: [], profiles: [], gaps: [], services: '' };
  let section = '';
  let step: PageStep | undefined;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const h2 = /^## (.+)/.exec(line);
    if (h2) {
      section = h2[1]!.trim().toLowerCase();
      step = undefined;
      continue;
    }
    const h3 = /^### (\d+)\. (.+)/.exec(line);
    if (h3 && section === 'steps') {
      step = { n: Number(h3[1]), title: h3[2]!.trim(), line: i + 1, blocks: [] };
      page.steps.push(step);
      continue;
    }
    const fence = FENCE.exec(line);
    if (fence) {
      const end = lines.findIndex((l, j) => j > i && l.startsWith('```'));
      const tab = fence[1] as Tab;
      if (end < 0) throw new Error(`${path}:${i + 1}: code block never closes`);
      if ((TABS as readonly string[]).includes(tab)) {
        const block = { tab, code: lines.slice(i + 1, end).join('\n'), line: i + 2 };
        if (section === 'before you start') page.setup.push(block);
        else if (step) step.blocks.push(block);
      }
      i = end;
      continue;
    }
    const cells = line.startsWith('|') ? line.split('|').slice(1, -1).map((c) => c.trim()) : [];
    if (!cells.length || cells.every((c) => /^-*$/.test(c))) continue;
    if (section === 'who is in it') {
      const profile = /`([^`]+)` profile/.exec(cells[2] ?? '');
      if (profile) page.profiles.push(profile[1]!);
    } else if (section === 'gaps' && cells[0] !== 'Product fix') {
      page.gaps.push({ line: i + 1, text: cells.join(' | ') });
    } else if (section === 'details' && cells[0] === 'Services the run starts') {
      page.services = cells[1] ?? '';
    }
  }
  return page;
}

/** The page whose use case table names `id` (`| Id | \`uc-676\` |`), searched one folder deep under docs/usecases. */
export function findPage(root: string, id: string): string | undefined {
  const base = join(root, 'docs/usecases');
  if (!existsSync(base)) return undefined;
  const mark = new RegExp(`^\\| Id \\| \`${id}\` \\|`, 'm');
  for (const area of readdirSync(base, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name).sort()) {
    for (const name of readdirSync(join(base, area)).filter((n) => n.endsWith('.md')).sort()) {
      const path = join('docs/usecases', area, name);
      if (mark.test(readFileSync(join(root, path), 'utf8'))) return path;
    }
  }
  return undefined;
}

function label(tab: Tab, page: Page, s: PageStep | undefined): string {
  return s ? `${tab} step ${s.n}: ${s.title} (${page.path}:${s.line})` : `${tab} before you start (${page.path}:${page.setup.find((b) => b.tab === tab)?.line ?? 0})`;
}

/** Steps that have no block in `tab`; each is a page that does not cover that tab yet. */
export function missingTabs(page: Page, tab: Tab): PageStep[] {
  return page.steps.filter((s) => !s.blocks.some((b) => b.tab === tab));
}

type Unit = { label: string; block: Block; step: boolean };

function units(page: Page, tab: Tab): Unit[] {
  const out: Unit[] = page.setup.filter((b) => b.tab === tab).map((block) => ({ label: label(tab, page, undefined), block, step: false }));
  for (const s of page.steps) for (const block of s.blocks.filter((b) => b.tab === tab)) out.push({ label: label(tab, page, s), block, step: true });
  return out;
}

/**
 * Python: each block compiled under the page's name with its page line numbers, run in one namespace, so a
 * traceback points at the page and later steps see earlier steps' names.
 */
export function pythonProgram(page: Page, sdkSrc: string, tab: Tab = 'Python'): string {
  const blocks = units(page, tab).map((u) => [u.label, u.block.line, u.block.code, u.step]);
  return [
    'import json, sys, traceback',
    `sys.path.insert(0, ${JSON.stringify(sdkSrc)})`,
    `BLOCKS = json.loads(${JSON.stringify(JSON.stringify(blocks))})`,
    'ns = {"__name__": "__main__"}',
    'for label, line, code, is_step in BLOCKS:',
    `    try:`,
    `        exec(compile("\\n" * (line - 1) + code, ${JSON.stringify(page.path)}, "exec"), ns)`,
    '    except BaseException as exc:',
    '        traceback.print_exc()',
    '        at = [f.lineno for f in traceback.extract_tb(exc.__traceback__) if f.filename == ' + JSON.stringify(page.path) + ']',
    `        print(f"FAIL {label}: {type(exc).__name__}: {exc}" + (f" at ${page.path}:{at[-1]}" if at else ""), flush=True)`,
    '        sys.exit(1)',
    '    if is_step:',
    '        print(f"PASS {label}", flush=True)',
    '',
  ].join('\n');
}

/**
 * TypeScript: imports hoisted (ESM allows them only at the top), every block in one try so a step sees the consts of
 * the steps before it, and the SDK import pointed at the built SDK. A failure names the page line from the stack.
 */
export function typescriptProgram(page: Page, sdkEntry: string): string {
  const head: string[] = [];
  const body: string[] = [];
  const map: Record<number, number> = {};
  const fixed = 3; // the lines written before the body
  for (const u of units(page, 'TypeScript')) {
    body.push(`step = ${JSON.stringify(u.label)};`);
    u.block.code.split('\n').forEach((code, k) => {
      if (/^import\s/.test(code)) {
        head.push(code.replace(/(['"])@chanl-ai\/ops-ai\1/, JSON.stringify(pathToFileURL(sdkEntry).href)));
        return;
      }
      body.push(code);
      map[body.length] = u.block.line + k;
    });
    if (u.step) body.push('console.log(`PASS ${step}`);');
  }
  const offset = head.length + fixed;
  const lines: Record<number, number> = Object.fromEntries(Object.entries(map).map(([g, p]) => [Number(g) + offset, p]));
  return [
    ...head,
    `const PAGE_LINES = ${JSON.stringify(lines)};`,
    "let step = '';",
    'try {',
    ...body,
    '} catch (e) {',
    '  console.error(e);',
    "  const at = /program\\.mts:(\\d+)/.exec(String((e as Error)?.stack ?? ''));",
    `  const line = at ? PAGE_LINES[Number(at[1])] : undefined;`,
    `  console.log(\`FAIL \${step}: \${String((e as Error)?.message ?? e).replace(/\\s*\\n\\s*/g, ' ')}\${line ? \` at ${page.path}:\${line}\` : ''}\`);`,
    '  process.exitCode = 1;',
    '}',
    '',
  ].join('\n');
}

/** CLI: bash with `set -eE` and an ERR trap that names the step and the page line of the command that failed. */
export function cliProgram(page: Page): string {
  const out = ['#!/usr/bin/env bash', 'set -eE', "STEP=''; OFF=0", `trap 'echo "FAIL $STEP: exit $? at ${page.path}:$((LINENO + OFF))"' ERR`];
  for (const u of units(page, 'CLI')) {
    out.push(`STEP=${JSON.stringify(u.label)}; OFF=${u.block.line - (out.length + 2)}`);
    out.push(...u.block.code.split('\n'));
    if (u.step) out.push('echo "PASS $STEP"');
  }
  return `${out.join('\n')}\n`;
}

/** The code of one page as files to open in an editor: one per tab, steps marked with their page line. */
export function extract(root: string, id: string): string[] {
  const path = findPage(root, id);
  if (!path) throw new Error(`no page names ${id} in its use case table under docs/usecases/`);
  const page = parsePage(readFileSync(join(root, path), 'utf8'), path);
  const dir = join(root, '.logs/usecases/pages', id);
  mkdirSync(dir, { recursive: true });
  const files: [string, Tab, string][] = [['python.py', 'Python', '#'], ['typescript.mts', 'TypeScript', '//'], ['cli.sh', 'CLI', '#'], ['mcp.py', 'MCP', '#']];
  return files.map(([name, tab, mark]) => {
    const text = units(page, tab).map((u) => `${mark} ${u.label}\n${u.block.code}`).join('\n\n');
    writeFileSync(join(dir, name), `${text}\n`);
    return relative(root, join(dir, name));
  });
}

/**
 * Fills in what a program could not say for itself: when it exits non-zero without a FAIL line (a bash `exit 1`, a
 * crash before the first step), the first step with no PASS fails with the output's tail.
 */
export function stepVerdicts(page: Page, tab: Tab, code: number | null, output: string): string[] {
  const extra: string[] = [];
  for (const s of missingTabs(page, tab)) extra.push(`FAIL ${label(tab, page, s)}: the page has no ${tab} tab for this step`);
  if (code !== 0 && !output.split('\n').some((l) => l.startsWith('FAIL '))) {
    const passed = new Set(output.split('\n').filter((l) => l.startsWith('PASS ')).map((l) => l.slice(5)));
    const first = units(page, tab).find((u) => u.step && !passed.has(u.label));
    const tail = output.trim().split('\n').slice(-3).join(' / ');
    extra.push(`FAIL ${first?.label ?? label(tab, page, undefined)}: exited ${code ?? 'by signal'}${tail ? `: ${tail}` : ''}`);
  }
  return extra;
}

/** Starts the page's stack (docs/usecases/lib/page_stack.py) and resolves once it has written the profiles. */
function startStack(root: string, page: Page, config: string, env: NodeJS.ProcessEnv): Promise<{ stop: () => Promise<void> }> {
  const argv = commandFor(root, 'docs/usecases/lib/page_stack.py', 'python');
  const args = ['--config', config, '--profiles', page.profiles.join(',') || 'default', '--services', page.services];
  return new Promise((resolve, reject) => {
    const child = spawn(argv[0]!, [...argv.slice(1), ...args], { cwd: root, env, stdio: ['pipe', 'pipe', 'pipe'] });
    let seen = '';
    const done = new Promise<void>((r) => child.on('close', () => r()));
    const read = (chunk: Buffer) => {
      seen += chunk.toString();
      if (/^READY$/m.test(seen)) resolve({ stop: () => (child.stdin.end(), done) });
    };
    child.stdout.on('data', read);
    child.stderr.on('data', (c: Buffer) => (seen += c.toString()));
    child.on('close', (c) => reject(new Error(`the page's stack stopped before it was ready (exit ${c}): ${seen.trim().split('\n').slice(-5).join(' / ')}`)));
  });
}

/** Runs one layer of a page: its stack, then one program per tab in order. Output follows report.ts's contract. */
export async function runPage(root: string, path: string, layer: Layer, env: NodeJS.ProcessEnv): Promise<{ code: number | null; output: string }> {
  const page = parsePage(readFileSync(join(root, path), 'utf8'), path);
  const tabs = LAYER_TABS[layer] ?? [];
  const dir = join(root, '.logs/usecases/pages', `${page.path.replace(/[^a-z0-9]+/gi, '-')}-${layer}-${process.pid}`);
  const work = join(dir, 'work');
  mkdirSync(work, { recursive: true });
  let output = '';
  const say = (line: string) => {
    output += `${line}\n`;
    console.log(line);
  };
  for (const g of page.gaps) say(`FAIL gap open (${page.path}:${g.line}): ${g.text}`);
  let code: number | null = 0;
  for (const [k, tab] of tabs.entries()) {
    // Each tab is its own run of the story: a fresh stack and, after the first, a fresh database, so the second tab
    // does not meet the first tab's knowledge base under the same name.
    const db = k ? runDatabaseName() : undefined;
    const tabEnv = db ? { ...env, [DB_VAR]: db } : env;
    const config = join(dir, `ops-config-${tab}.json`);
    let stack: { stop: () => Promise<void> };
    try {
      stack = await startStack(root, page, config, tabEnv);
    } catch (e) {
      say(`FAIL ${tab} stack for ${page.path}: ${(e as Error).message}`);
      code = 1;
      if (db) await dropDatabase(root, env, db);
      continue;
    }
    try {
      const ran = await runTab(root, page, tab, dir, work, { ...tabEnv, OPS_CONFIG: config }, say);
      output += ran.output;
      for (const line of stepVerdicts(page, tab, ran.code, ran.output)) say(line);
      if (ran.code !== 0) code = ran.code;
    } finally {
      await stack.stop();
      if (db && !(await dropDatabase(root, env, db))) console.error(`could not drop ${db}; make usecase-reset drops leftovers`);
    }
  }
  return { code, output };
}

async function runTab(root: string, page: Page, tab: Tab, dir: string, work: string, env: NodeJS.ProcessEnv, say: (line: string) => void): Promise<{ code: number | null; output: string }> {
  if (tab === 'Python' || tab === 'MCP') {
    writeFileSync(join(dir, 'program.py'), pythonProgram(page, join(root, 'sdk/python/src'), tab));
    return runScript(commandFor(root, relative(root, join(dir, 'program.py')), 'python'), env, work);
  }
  if (tab === 'TypeScript') {
    const built = await runScript(['npx', 'tsc', '-p', 'tsconfig.json'], env, join(root, 'sdk/typescript'));
    if (built.code !== 0) {
      say(`FAIL ${tab} build of sdk/typescript: ${built.output.trim().split('\n').slice(-3).join(' / ')}`);
      return { code: 1, output: '' };
    }
    writeFileSync(join(dir, 'program.mts'), typescriptProgram(page, join(root, 'sdk/typescript/dist/index.js')));
    return runScript([process.execPath, join(dir, 'program.mts')], env, work);
  }
  writeFileSync(join(dir, 'program.sh'), cliProgram(page));
  // uv puts sdk/python's environment, and so `opsai`, on PATH.
  return runScript(['uv', 'run', '--quiet', '--project', join(root, 'sdk/python'), 'bash', join(dir, 'program.sh')], env, work);
}

export function hasPageTabs(root: string, path: string, layer: Layer): boolean {
  if (!existsSync(join(root, path))) return false;
  const page = parsePage(readFileSync(join(root, path), 'utf8'), path);
  return (LAYER_TABS[layer] ?? []).some((tab) => page.steps.some((s) => s.blocks.some((b) => b.tab === tab)));
}
