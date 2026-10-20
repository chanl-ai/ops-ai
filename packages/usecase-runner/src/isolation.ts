// What one `test` run owns so that runs from different sessions never meet: its own database and its own ports. A
// value the caller set explicitly is used as given; anything unset is chosen here, per run.
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { createServer } from 'node:net';
import { join } from 'node:path';

export const PORT_VARS = ['OPS_USECASE_AGENTS_PORT', 'OPS_USECASE_TOOLS_PORT', 'OPS_USECASE_MODELS_PORT', 'OPS_USECASE_CONSOLE_PORT', 'OPS_USECASE_PLATFORM_PORT', 'OPS_USECASE_PLATFORM_INTERNAL_PORT', 'OPS_USECASE_KB_PORT', 'OPS_USECASE_FAKE_OPENAI_PORT', 'OPS_USECASE_FILES_PORT', 'OPS_USECASE_DOCUMENTS_PORT', 'OPS_USECASE_EMBED_PORT', 'OPS_USECASE_IDP_PORT'] as const;
export const DB_VAR = 'OPS_USECASE_DB';
// The local stack's ports (make/env.mk), shared and ISOLATED=1. A run never takes one, even when the OS offers it.
const STACK_VARS = ['OPS_CONSOLE_PORT', 'OPS_CONSOLE_RUNTIME_PORT', 'OPS_AGENTS_PORT', 'OPS_TOOLS_PORT', 'OPS_KB_PORT', 'OPS_OPA_PORT', 'OPS_PG_PORT', 'OPS_PLATFORM_PORT', 'OPS_PLATFORM_INTERNAL_PORT', 'OPS_FILES_PORT', 'OPS_DOCUMENTS_PORT'];
const STACK_DEFAULTS = [3016, 3017, 8700, 8720, 8740, 8181, 5477, 8710, 8711, 8750, 8760].flatMap((p) => [p, p + 1000]);

function freePort(): Promise<number> {
  return new Promise((done, fail) => {
    const s = createServer();
    s.once('error', fail);
    s.listen(0, '127.0.0.1', () => {
      const port = (s.address() as { port: number }).port;
      s.close(() => done(port));
    });
  });
}

export interface RunResources {
  env: NodeJS.ProcessEnv;
  /** The database this run created a name for and drops at the end; undefined when the caller named one. */
  ownedDb?: string;
}

/** The child environment with every unset OPS_USECASE_* filled with this run's own value. */
export async function isolate(env: NodeJS.ProcessEnv): Promise<RunResources> {
  const out: NodeJS.ProcessEnv = { ...env };
  const taken = new Set<number>([...STACK_DEFAULTS, ...STACK_VARS.map((k) => Number(env[k])).filter(Number.isInteger)]);
  for (const k of PORT_VARS) if (env[k]) taken.add(Number(env[k]));
  for (const k of PORT_VARS) {
    if (env[k]) continue;
    let port = await freePort();
    while (taken.has(port)) port = await freePort();
    taken.add(port);
    out[k] = String(port);
  }
  if (env[DB_VAR]) return { env: out };
  // The scripts' scripted server creates it on first use (CREATE DATABASE when missing).
  const name = `ops_usecase_r${process.pid}_${randomBytes(3).toString('hex')}`;
  out[DB_VAR] = name;
  return { env: out, ownedDb: name };
}

const DROP = `
import asyncio, os, sys, asyncpg
async def main():
    c = await asyncpg.connect(f"postgresql://ops:ops@localhost:{os.environ.get('OPS_PG_PORT', '5477')}/postgres")
    try:
        await c.execute(f'DROP DATABASE IF EXISTS "{sys.argv[1]}" WITH (FORCE)')
    finally:
        await c.close()
asyncio.run(main())
`;

/** Drops a database this run created, through the agents-service project (it holds asyncpg). */
export function dropDatabase(root: string, env: NodeJS.ProcessEnv, name: string): Promise<boolean> {
  return new Promise((done) => {
    const argv = ['run', '--quiet', '--directory', join(root, 'services/agents-service'), 'python', '-c', DROP, name];
    const child = spawn('uv', argv, { env, stdio: ['ignore', 'ignore', 'inherit'] });
    child.on('error', () => done(false));
    child.on('close', (code) => done(code === 0));
  });
}

/** Drops the scratch databases of runs that are over (scripts/scratch_db_sweep.py), before this run makes its own, so a
 * run that was killed leaves its database for one run at most. A sweep that fails only warns. */
export function sweepFinished(root: string, env: NodeJS.ProcessEnv): Promise<boolean> {
  return new Promise((done) => {
    const argv = ['run', '--quiet', '--project', root, 'python', join(root, 'scripts/scratch_db_sweep.py')];
    const child = spawn('uv', argv, { env, stdio: ['ignore', 'inherit', 'inherit'] });
    child.on('error', () => done(false));
    child.on('close', (code) => done(code === 0));
  });
}
