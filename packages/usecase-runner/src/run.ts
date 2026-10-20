// Runs one resolved script and returns its exit code and output. Python scripts run in the agents-service uv project,
// which holds the workspace packages they import; Node scripts run with the repo's node.
import { spawn } from 'node:child_process';
import { join } from 'node:path';

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
  return { env, realCalls };
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
