// Runs one resolved script and returns its exit code and output. Python scripts run in the agents-service uv project,
// which holds the workspace packages they import; Node scripts run with the repo's node.
import { execFileSync, spawn } from 'node:child_process';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';

const MODEL_KEYS = ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY'];

/**
 * The child's environment. Model keys are removed unless APPROVED_REAL_CALLS is a positive count the owner approved,
 * so a script that reaches a real provider by mistake fails on a missing key instead of spending money.
 */
export function childEnv(parent: NodeJS.ProcessEnv, root: string): { env: NodeJS.ProcessEnv; realCalls: number } {
  const env: NodeJS.ProcessEnv = { ...parent };
  delete env.VIRTUAL_ENV;
  const approved = Number.parseInt(parent.APPROVED_REAL_CALLS ?? '', 10);
  const realCalls = Number.isInteger(approved) && approved > 0 ? approved : 0;
  if (!realCalls) for (const k of MODEL_KEYS) delete env[k];
  env.PYTHONPATH = [join(root, 'docs/usecases/lib'), parent.PYTHONPATH].filter(Boolean).join(':');
  // The ui harness starts this tree's services: from an export it would otherwise resolve, through the installed
  // package, to whichever tree node_modules points at.
  env.OPS_USECASE_ROOT = root;
  const plugins = env.OPS_PLUGINS_REPO ? undefined : defaultPluginsRepo(root);
  if (plugins) env.OPS_PLUGINS_REPO = plugins;
  return { env, realCalls };
}

/**
 * ops-ai-plugins beside the main checkout. A linked worktree sits somewhere else, so the folder is found through git's
 * common directory, which is the main checkout's `.git` from every worktree. Undefined when git cannot say.
 */
export function defaultPluginsRepo(root: string): string | undefined {
  try {
    const common = execFileSync('git', ['-C', root, 'rev-parse', '--path-format=absolute', '--git-common-dir'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    const main = basename(common) === '.git' ? dirname(common) : common;
    return join(dirname(main), 'ops-ai-plugins');
  } catch {
    return undefined;
  }
}

const NEEDS_PLUGINS = /PLUGINS_REPO|ops-ai-plugins/;

function needsPlugins(source: string): boolean {
  return NEEDS_PLUGINS.test(source);
}

/**
 * A script that gets the plugins path through a shared module (several_accounts, templates_stack) never names it
 * itself. usecase_harness is left out: it defines PLUGINS_REPO for every Python script, so a script that uses it names it.
 */
function libraryNeedsPlugins(source: string, scriptPath: string): boolean {
  const lib = join(dirname(scriptPath), '..', '..', 'lib');
  if (!existsSync(lib)) return false;
  return readdirSync(lib)
    .filter((f) => /\.(py|mjs|js|ts)$/.test(f) && !f.startsWith('usecase_harness'))
    .some((f) => {
      const name = f.replace(/\.[^.]+$/, '');
      return new RegExp(`\\b${name}\\b`).test(source) && needsPlugins(readFileSync(join(lib, f), 'utf8'));
    });
}

/** The one line a run stops with when a script reads OPS_PLUGINS_REPO and the repo is not where it defaults to. */
export function pluginsRepoRefusal(env: NodeJS.ProcessEnv, scriptPath: string): string | undefined {
  const repo = env.OPS_PLUGINS_REPO;
  if (!repo || existsSync(repo)) return undefined;
  const source = readFileSync(scriptPath, 'utf8');
  if (!needsPlugins(source) && !libraryNeedsPlugins(source, scriptPath)) return undefined;
  return `FAIL the plugins repository is not at ${repo}; clone ops-ai-plugins there or set OPS_PLUGINS_REPO to its folder`;
}

export function commandFor(root: string, path: string, runtime: 'python' | 'node'): string[] {
  const abs = join(root, path);
  return runtime === 'python'
    ? ['uv', 'run', '--quiet', '--directory', join(root, 'services/agents-service'), 'python', abs]
    : [process.execPath, abs];
}

export function runScript(argv: string[], env: NodeJS.ProcessEnv, cwd: string): Promise<{ code: number | null; output: string }> {
  return new Promise((resolve) => {
    const child = spawn(argv[0]!, argv.slice(1), { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] });
    let output = '';
    const relay = (chunk: Buffer, to: NodeJS.WriteStream) => {
      output += chunk.toString();
      to.write(chunk);
    };
    child.stdout.on('data', (c: Buffer) => relay(c, process.stdout));
    child.stderr.on('data', (c: Buffer) => relay(c, process.stderr));
    child.on('error', (e) => resolve({ code: 127, output: `${output}\nFAIL could not start ${argv[0]}: ${e.message}` }));
    child.on('close', (code) => resolve({ code, output }));
  });
}
