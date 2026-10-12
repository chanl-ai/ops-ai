// Entry for scripts/usecase.mjs: list | show <id> | test [--uc <id>] [--layer <layer>] | coverage <service> |
// new <service> "<title>". Exit codes are in report.ts (EXIT).
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { coverage, formatCoverage } from './coverage.ts';
import { isLayer, LAYERS, type Layer } from './layers.ts';
import { findUseCase, parseRegistry, RegistryError, type UseCase } from './registry.ts';
import { EXIT, exitFor, parseChecks, summary, verdict, type Outcome } from './report.ts';
import { dropDatabase, isolate } from './isolation.ts';
import { resolveScript, USECASE_DIR } from './resolve.ts';
import { childEnv, commandFor, runScript } from './run.ts';
import { scaffold } from './scaffold.ts';

function flag(args: string[], name: string): string | undefined {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : undefined;
}

function loadRegistry(root: string): UseCase[] {
  return parseRegistry(readFileSync(join(root, USECASE_DIR, 'README.md'), 'utf8'));
}

/** What a test run uses beside the registry: the parent environment and how it drops the database it created. */
export interface TestDeps {
  parent: NodeJS.ProcessEnv;
  drop: (root: string, env: NodeJS.ProcessEnv, name: string) => Promise<boolean>;
}

export async function test(
  root: string,
  registry: UseCase[],
  ucId: string | undefined,
  layerArg: string | undefined,
  deps: TestDeps = { parent: process.env, drop: dropDatabase },
): Promise<number> {
  if (layerArg && !isLayer(layerArg)) {
    console.error(`unknown layer ${layerArg}; one of ${LAYERS.join(', ')}`);
    return EXIT.usage;
  }
  const targets = ucId ? [findUseCase(registry, ucId)] : registry;
  const { env: base, realCalls } = childEnv(deps.parent, root);
  console.log(realCalls ? `real model calls approved: ${realCalls}` : 'scripted model only (model keys removed; APPROVED_REAL_CALLS=<n> to allow real calls)');
  const { env, ownedDb } = await isolate(base);
  console.log(`database ${env.OPS_USECASE_DB}${ownedDb ? ' (this run\'s, dropped at the end)' : ''}; ports agents ${env.OPS_USECASE_AGENTS_PORT}, tools ${env.OPS_USECASE_TOOLS_PORT}, models ${env.OPS_USECASE_MODELS_PORT}, platform ${env.OPS_USECASE_PLATFORM_PORT}, console ${env.OPS_USECASE_CONSOLE_PORT}`);
  try {
    return await runAll(root, targets, layerArg, env);
  } finally {
    if (ownedDb && !(await deps.drop(root, env, ownedDb))) console.error(`could not drop ${ownedDb}; make usecase-reset drops leftovers`);
  }
}

async function runAll(root: string, targets: UseCase[], layerArg: string | undefined, env: NodeJS.ProcessEnv): Promise<number> {
  const outcomes: Outcome[] = [];
  for (const uc of targets) {
    const layers: Layer[] = layerArg ? [layerArg as Layer] : uc.layers;
    for (const layer of layers) {
      const r = resolveScript(root, uc, layer);
      if (r.kind === 'unavailable') {
        outcomes.push({ id: uc.id, layer, status: 'UNAVAILABLE', detail: r.reason });
        continue;
      }
      if (r.kind === 'missing') {
        outcomes.push({ id: uc.id, layer, status: 'FAIL', detail: r.reason });
        continue;
      }
      console.log(`\n== ${uc.id} ${layer}: ${uc.title} (${r.path})`);
      const { code, output } = await runScript(commandFor(root, r.path, r.runtime), env, root);
      const checks = parseChecks(output);
      const v = verdict(code, checks);
      outcomes.push({
        id: uc.id,
        layer,
        status: v.pass ? 'PASS' : 'FAIL',
        detail: v.pass ? `${checks.passed.length} checks passed` : `${v.reason}; ${checks.passed.length} passed, ${checks.failed.length} failed`,
      });
    }
  }
  console.log(`\n${summary(outcomes)}`);
  return exitFor(outcomes);
}

export async function main(argv: string[], root: string): Promise<number> {
  const [cmd = 'list', ...rest] = argv;
  try {
    if (cmd === 'new') {
      const [service, title] = rest;
      if (!service || !title) {
        console.error('usage: new <service> "<title>"');
        return EXIT.usage;
      }
      const made = scaffold(root, loadRegistry(root), service, title);
      console.log(`created ${made.id}:\n  ${made.files.join('\n  ')}`);
      return EXIT.ok;
    }
    const registry = loadRegistry(root);
    if (cmd === 'list') {
      console.log(registry.map((u) => `${u.id}  ${u.service.padEnd(16)} ${u.layers.join(',').padEnd(8)} ${u.status.padEnd(8)} ${u.title}`).join('\n'));
      return EXIT.ok;
    }
    if (cmd === 'show') {
      const uc = findUseCase(registry, rest[0] ?? '');
      const lines = LAYERS.map((l) => {
        const r = resolveScript(root, uc, l);
        return `  ${l.padEnd(4)} ${r.kind === 'script' ? r.path : r.reason}${uc.layers.includes(l) ? '' : ' (not required)'}`;
      });
      console.log(`${uc.id} ${uc.title}\n  service ${uc.service} · status ${uc.status}\n${lines.join('\n')}`);
      return EXIT.ok;
    }
    if (cmd === 'coverage') {
      const service = rest[0];
      const services = service ? [service] : [...new Set(registry.map((u) => u.service))];
      console.log(services.map((s) => formatCoverage(s, coverage(root, registry, s))).join('\n\n'));
      return EXIT.ok;
    }
    if (cmd === 'test') return await test(root, registry, flag(rest, 'uc'), flag(rest, 'layer'));
    console.error(`unknown command ${cmd}; one of list, show, test, coverage, new`);
    return EXIT.usage;
  } catch (e) {
    if (e instanceof RegistryError) {
      console.error(e.message);
      return EXIT.usage;
    }
    throw e;
  }
}
