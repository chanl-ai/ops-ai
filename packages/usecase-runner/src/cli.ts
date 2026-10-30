// Entry for scripts/usecase.mjs: list | show <id> | test [--uc <id>] [--layer <layer>] | report [--uc <id>] |
// coverage <service> | new <service> "<title>". Exit codes are in report.ts (EXIT).
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { coverage, formatCoverage } from './coverage.ts';
import { isLayer, LAYERS, type Layer } from './layers.ts';
import { findUseCase, parseRegistry, RegistryError, type UseCase } from './registry.ts';
import { EXIT, exitFor, parseChecks, summary, verdict, type Outcome } from './report.ts';
import { DB_VAR, dropDatabase, isolate, rebuildIfStale, runDatabaseName, sweepFinished } from './isolation.ts';
import { resolveScript, USECASE_DIR } from './resolve.ts';
import { childEnv, commandFor, runScript } from './run.ts';
import { scaffold } from './scaffold.ts';
import { formatStories, loadRun, saveRun, storiesOf, StoryError, type SavedRun } from './stories.ts';

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
  /** Drops finished runs' scratch databases before this run starts; absent in the runner's own tests. */
  sweep?: (root: string, env: NodeJS.ProcessEnv) => Promise<boolean>;
  /** Rebuilds a database the caller named whose chains are behind; absent in the runner's own tests. */
  rebuild?: (root: string, env: NodeJS.ProcessEnv, name: string) => Promise<boolean>;
}

export async function test(
  root: string,
  registry: UseCase[],
  ucId: string | undefined,
  layerArg: string | undefined,
  deps: TestDeps = { parent: process.env, drop: dropDatabase, sweep: sweepFinished, rebuild: rebuildIfStale },
): Promise<number> {
  if (layerArg && !isLayer(layerArg)) {
    console.error(`unknown layer ${layerArg}; one of ${LAYERS.join(', ')}`);
    return EXIT.usage;
  }
  const targets = ucId ? [findUseCase(registry, ucId)] : registry;
  const { env: base, realCalls } = childEnv(deps.parent, root);
  console.log(realCalls ? `real model calls approved: ${realCalls}` : 'scripted model only (model keys removed; APPROVED_REAL_CALLS=<n> to allow real calls)');
  if (deps.sweep && !(await deps.sweep(root, base))) console.error('could not sweep finished runs\' databases; make db-sweep retries');
  const { env, ownedDb } = await isolate(base);
  if (!ownedDb && deps.rebuild && !(await deps.rebuild(root, env, String(env[DB_VAR])))) {
    console.error(`could not check ${env[DB_VAR]}'s migrations; a chain behind may stop the scripts at start`);
  }
  // Each script gets its own database when the run owns the name: a stack's files folder is new per script, so rows an
  // earlier script left behind name files that are gone, and kb-service's startup seed failed on them (c-553).
  let current: string | undefined;
  const databaseFor = ownedDb
    ? async (run: (env: NodeJS.ProcessEnv) => Promise<Outcome>) => {
        current = runDatabaseName();
        try {
          return await run({ ...env, [DB_VAR]: current });
        } finally {
          if (!(await deps.drop(root, env, current))) console.error(`could not drop ${current}; make usecase-reset drops leftovers`);
          current = undefined;
        }
      }
    : (run: (env: NodeJS.ProcessEnv) => Promise<Outcome>) => run(env);
  // A run stopped with Ctrl-C or a kill still drops the database it made; the sweep catches a run killed harder.
  const stop = (signal: NodeJS.Signals) => {
    void (current ? deps.drop(root, env, current) : Promise.resolve(true)).finally(() => process.exit(signal === 'SIGINT' ? 130 : 143));
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  console.log(`database ${ownedDb ? 'one per use case, each dropped after it' : env.OPS_USECASE_DB}; ports agents ${env.OPS_USECASE_AGENTS_PORT}, tools ${env.OPS_USECASE_TOOLS_PORT}, models ${env.OPS_USECASE_MODELS_PORT}, kb ${env.OPS_USECASE_KB_PORT}, files ${env.OPS_USECASE_FILES_PORT}, fake openai ${env.OPS_USECASE_FAKE_OPENAI_PORT}, platform ${env.OPS_USECASE_PLATFORM_PORT}, console ${env.OPS_USECASE_CONSOLE_PORT}`);
  return await runAll(root, targets, layerArg, databaseFor);
}

async function runAll(
  root: string,
  targets: UseCase[],
  layerArg: string | undefined,
  databaseFor: (run: (env: NodeJS.ProcessEnv) => Promise<Outcome>) => Promise<Outcome>,
): Promise<number> {
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
      outcomes.push(
        await databaseFor(async (env) => {
          const { code, output } = await runScript(commandFor(root, r.path, r.runtime), env, root);
          const checks = parseChecks(output);
          saveRun(root, { id: uc.id, layer, at: new Date().toISOString(), exit: code, checks });
          const v = verdict(code, checks);
          return {
            id: uc.id,
            layer,
            status: v.pass ? 'PASS' : 'FAIL',
            detail: v.pass ? `${checks.passed.length} checks passed` : `${v.reason}; ${checks.passed.length} passed, ${checks.failed.length} failed`,
          };
        }),
      );
    }
  }
  const stories = report(root, targets.filter((uc) => outcomes.some((o) => o.id === uc.id && o.status !== 'UNAVAILABLE')), layerArg as Layer | undefined);
  console.log(`\n${stories ? `Stories\n${stories}\n\n` : ''}${summary(outcomes)}`);
  return exitFor(outcomes);
}

/**
 * The stories block for each use case, from the latest saved run of each layer (only `layer` when given). A use case
 * whose doc has no Stories table says so rather than being left out.
 */
export function report(root: string, targets: UseCase[], layer?: Layer): string {
  return targets
    .map((uc) => {
      const { stories } = storiesOf(root, uc);
      const shown = layer ? stories.filter((s) => s.layer === layer) : stories;
      const runs: Partial<Record<Layer, SavedRun>> = {};
      for (const l of new Set(shown.map((s) => s.layer))) runs[l] = loadRun(root, uc.id, l);
      return formatStories(uc, shown, runs);
    })
    .join('\n\n');
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
    if (cmd === 'report') {
      const ucId = flag(rest, 'uc');
      const targets = ucId ? [findUseCase(registry, ucId)] : registry.filter((uc) => storiesOf(root, uc).stories.length);
      console.log(targets.length ? report(root, targets) : 'no use case has a Stories table yet');
      return EXIT.ok;
    }
    console.error(`unknown command ${cmd}; one of list, show, test, report, coverage, new`);
    return EXIT.usage;
  } catch (e) {
    if (e instanceof RegistryError || e instanceof StoryError) {
      console.error(e.message);
      return EXIT.usage;
    }
    throw e;
  }
}
