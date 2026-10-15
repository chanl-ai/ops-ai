// What a Node use case script (the ui layer) shares with the Python harness in docs/usecases/lib: PASS/FAIL checks,
// and services started fresh on the use-case ports. The ui stack is the agents service on the scripted model plus a
// console dev server whose chat points at it, so a browser test never reaches a model provider or another session's
// console.
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { mkdirSync, openSync, rmSync } from 'node:fs';
import { createConnection } from 'node:net';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export { chromium } from 'playwright';

/** The tree the runner was invoked from (OPS_USECASE_ROOT, set by the runner), else the one this package sits in. */
export const ROOT = process.env.OPS_USECASE_ROOT ?? resolve(fileURLToPath(new URL('.', import.meta.url)), '../../..');
export const AGENTS_PORT = Number(process.env.OPS_USECASE_AGENTS_PORT ?? 8790);
export const CONSOLE_PORT = Number(process.env.OPS_USECASE_CONSOLE_PORT ?? 3018);
export const PLATFORM_PORT = Number(process.env.OPS_USECASE_PLATFORM_PORT ?? 8810);
const PLATFORM_INTERNAL_PORT = Number(process.env.OPS_USECASE_PLATFORM_INTERNAL_PORT ?? 8811);
export const TOOLS_PORT = Number(process.env.OPS_USECASE_TOOLS_PORT ?? 8792);
const CONSOLE_DIST_DIR = `node_modules/.cache/next-usecase-${CONSOLE_PORT}`;
const DB = process.env.OPS_USECASE_DB ?? 'ops_usecase';
const LOG_DIR = join(process.env.OPS_LOG_DIR ?? join(ROOT, '.logs'), 'usecase');

let checked = 0;
let failed = 0;

export function check(name: string, ok: boolean, detail: unknown = ''): boolean {
  checked++;
  if (ok) console.log(`PASS ${name}`);
  else {
    failed++;
    console.log(`FAIL ${name}: ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`);
  }
  return ok;
}

export function finish(): never {
  if (!checked) console.log('FAIL no checks ran');
  process.exit(!checked || failed ? 1 : 0);
}

export function portBusy(port: number): Promise<boolean> {
  return new Promise((done) => {
    const s = createConnection({ port, host: '127.0.0.1' });
    s.once('connect', () => (s.destroy(), done(true)));
    s.once('error', () => done(false));
  });
}

async function waitFor(url: string, child: ChildProcess, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`process for ${url} exited with ${child.exitCode}; see ${LOG_DIR}`);
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`${url} not ready after ${timeoutMs / 1000}s; see ${LOG_DIR}`);
}

export async function serve(name: string, port: number, argv: string[], cwd: string, env: NodeJS.ProcessEnv, ready: string, timeoutMs: number): Promise<ChildProcess> {
  // A stack stopped just before (a script with two stacks) frees its ports a moment after the signal.
  for (let i = 0; i < 40 && (await portBusy(port)); i++) await new Promise((r) => setTimeout(r, 250));
  if (await portBusy(port)) throw new Error(`port ${port} is already in use; stop that process or set OPS_USECASE_*_PORT`);
  mkdirSync(LOG_DIR, { recursive: true });
  const log = openSync(join(LOG_DIR, `${name}-${port}.log`), 'a');
  const child = spawn(argv[0]!, argv.slice(1), { cwd, env, stdio: ['ignore', log, log], detached: true });
  try {
    await waitFor(ready, child, timeoutMs);
  } catch (e) {
    // A service that never got healthy still holds its port; leaving it running fails the next run on a busy port.
    stop(child);
    throw e;
  }
  return child;
}

function stop(child: ChildProcess): void {
  // Each service runs in its own process group so the wrapper (uv, pnpm) and the server it started stop together.
  try {
    process.kill(-child.pid!, 'SIGTERM');
  } catch {
    // already gone
  }
}

/** Runs a command to its end, its output in the use-case log; rejects on a non-zero exit. */
function runToEnd(name: string, argv: string[], cwd: string, env: NodeJS.ProcessEnv): Promise<void> {
  mkdirSync(LOG_DIR, { recursive: true });
  const log = openSync(join(LOG_DIR, `${name}.log`), 'a');
  return new Promise((done, fail) => {
    const child = spawn(argv[0]!, argv.slice(1), { cwd, env, stdio: ['ignore', log, log] });
    child.on('error', fail);
    child.on('close', (code) => (code === 0 ? done() : fail(new Error(`${name} exited with ${code}; see ${LOG_DIR}`))));
  });
}

/** What a use case sets on the services its stack starts, beside the runner's own environment. */
export interface StackOptions {
  /** Settings for the agents service, e.g. `{ OPS_REGISTRY_AUTO_APPROVE: 'false' }` to keep publish requests pending. */
  agentsEnv?: Record<string, string>;
  /**
   * Also start platform-service on the run's database (its own migration chain, the dev seed of team_ops with Priya,
   * James and Maya) and sign the console in through it, so every call carries a person's token.
   */
  platform?: boolean;
  /**
   * Also start tools-service on the run's database (its migration chain and dev seed), deciding with a private OPA,
   * and point the console's Tools pages at it. `bank` adds the https fake bank on this machine's private address
   * (docs/usecases/lib/fake_bank_https.py), which tools-service reaches as `https://api.bank.test`.
   */
  tools?: {
    bank?: boolean;
    /** Point the agents service at this tools-service as its gateway, so agents are granted and call its operations. */
    gateway?: boolean;
  };
}

/** What the stack started, for a use case to drive: the fake bank's host and the private range it serves on. */
export interface Stack {
  bank?: { host: string; range: string };
}

/** The OPA tools-service writes its key and policy into: a container of its own, like ops_service_kit.opa_server. */
async function startOpa(): Promise<{ url: string; stop: () => void }> {
  const policy = join(ROOT, 'services/tools-service/policy');
  const cid = execFileSync('docker', ['run', '-d', '--rm', '-p', '127.0.0.1::8181', '-v', `${policy}:/policy:ro`, 'openpolicyagent/opa:1.21.1', 'run', '--server', '--addr', '0.0.0.0:8181', '--log-level', 'error', '/policy'], { encoding: 'utf8' }).trim();
  const stopOpa = () => {
    try {
      execFileSync('docker', ['rm', '-f', cid], { stdio: 'ignore' });
    } catch {
      // already gone
    }
  };
  try {
    const port = execFileSync('docker', ['port', cid, '8181/tcp'], { encoding: 'utf8' }).split('\n')[0]!.split(':').pop();
    const url = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 100; i++) {
      if (await fetch(`${url}/health`).then((r) => r.ok, () => false)) return { url, stop: stopOpa };
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(`OPA container ${cid.slice(0, 12)} did not become healthy`);
  } catch (e) {
    stopOpa();
    throw e;
  }
}

/** The fake bank, run by docs/usecases/lib/fake_bank_serve.py; resolves once it prints how to reach it. */
function startBank(): Promise<{ info: { settings: Record<string, string>; range: string; host: string }; child: ChildProcess }> {
  const env = { ...stackEnv(process.env), PYTHONPATH: [join(ROOT, 'docs/usecases/lib'), process.env.PYTHONPATH].filter(Boolean).join(':') };
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_bank_serve.py')], { env, stdio: ['pipe', 'pipe', 'inherit'], detached: true });
  return new Promise((done, fail) => {
    let out = '';
    child.stdout!.on('data', (d: Buffer) => {
      out += d.toString();
      const line = out.split('\n')[0];
      if (out.includes('\n')) done({ info: JSON.parse(line!), child });
    });
    child.on('error', fail);
    child.on('close', (code) => fail(new Error(`fake bank exited with ${code} before it was ready`)));
  });
}

/** The services' environment: the caller's, without model keys (scripted model only) or a stray venv, plus `extra`. */
export function stackEnv(base: NodeJS.ProcessEnv, extra: Record<string, string> = {}): NodeJS.ProcessEnv {
  const env = { ...base, ...extra };
  delete env.OPENAI_API_KEY;
  delete env.ANTHROPIC_API_KEY;
  delete env.VIRTUAL_ENV;
  return env;
}

/** The agents service on the scripted model plus a console whose chat calls it. Stops both when `body` returns. */
export async function withUiStack<T>(body: (consoleUrl: string, stack: Stack) => Promise<T>, options: StackOptions = {}): Promise<T> {
  const env = stackEnv(process.env);
  const consoleUrl = `http://localhost:${CONSOLE_PORT}`;
  const agents = await serve(
    'agents',
    AGENTS_PORT,
    [
      'uv', 'run', 'python', 'scripts/scripted_server.py', '--port', String(AGENTS_PORT), '--db', DB, '--cors', consoleUrl,
      // Agents take their tools from tools-service's registry; tools-service starts below, and is asked on first use.
      ...(options.tools?.gateway ? ['--gateway-url', `http://127.0.0.1:${TOOLS_PORT}`] : []),
    ],
    join(ROOT, 'services/agents-service'),
    // Under platform sign-in the agents service verifies the console's tokens against platform-service (started
    // below on known ports; its key set is read on first use), so dev headers no longer work there.
    stackEnv(process.env, {
      ...(options.platform ? { OPS_AUTH_MODE: 'platform', OPS_PLATFORM_URL: `http://127.0.0.1:${PLATFORM_PORT}`, OPS_PLATFORM_INTERNAL_PORT: String(PLATFORM_INTERNAL_PORT) } : {}),
      ...options.agentsEnv,
    }),
    `http://127.0.0.1:${AGENTS_PORT}/health`,
    90_000,
  );
  let consoleProc: ChildProcess | undefined;
  let platformProc: ChildProcess | undefined;
  let toolsProc: ChildProcess | undefined;
  let bankProc: ChildProcess | undefined;
  let opa: { url: string; stop: () => void } | undefined;
  const stack: Stack = {};
  try {
    const signIn: Record<string, string> = {};
    const toolsUrl: Record<string, string> = {};
    if (options.tools) {
      const toolsDir = join(ROOT, 'services/tools-service');
      const bankSettings: Record<string, string> = {};
      if (options.tools.bank) {
        const bank = await startBank();
        bankProc = bank.child;
        Object.assign(bankSettings, bank.info.settings);
        stack.bank = { host: bank.info.host, range: bank.info.range };
      }
      opa = await startOpa();
      const toolsEnv = stackEnv(process.env, {
        OPS_DATABASE_URL: `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`,
        OPS_GATEWAY_PORT: String(TOOLS_PORT),
        OPS_OPA_URL: opa.url,
        OPS_CORS_ORIGINS: JSON.stringify([consoleUrl]),
        // Workflow approvals name agents-service's workflows (c-039); without this tools-service would ask the dev port.
        OPS_AGENTS_URL: `http://127.0.0.1:${AGENTS_PORT}`,
        // Under platform sign-in tools-service verifies the console's tokens too, so people are told apart by role.
        ...(options.platform ? { OPS_AUTH_MODE: 'platform', OPS_PLATFORM_URL: `http://127.0.0.1:${PLATFORM_PORT}`, OPS_PLATFORM_INTERNAL_PORT: String(PLATFORM_INTERNAL_PORT) } : {}),
        ...bankSettings,
      });
      await runToEnd('tools-migrate', ['uv', 'run', 'alembic', 'upgrade', 'head'], toolsDir, toolsEnv);
      toolsProc = await serve('tools', TOOLS_PORT, ['uv', 'run', 'python', '-m', 'ops_tools'], toolsDir, toolsEnv, `http://127.0.0.1:${TOOLS_PORT}/health`, 90_000);
      toolsUrl.NEXT_PUBLIC_OPS_TOOLS_API_URL = `http://127.0.0.1:${TOOLS_PORT}`;
    }
    if (options.platform) {
      const platformDir = join(ROOT, 'services/platform-service');
      // The agents service created the run's database on start; platform-service adds its own tables beside them.
      const platformEnv = stackEnv(process.env, {
        OPS_DATABASE_URL: `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`,
        OPS_PLATFORM_PORT: String(PLATFORM_PORT),
        OPS_PLATFORM_INTERNAL_PORT: String(PLATFORM_INTERNAL_PORT),
        OPS_CORS_ORIGINS: JSON.stringify([consoleUrl]),
      });
      await runToEnd('platform-migrate', ['uv', 'run', 'alembic', 'upgrade', 'head'], platformDir, platformEnv);
      // Dev mode seeds on start. The public app has no /health; the key set answers once it serves.
      platformProc = await serve('platform', PLATFORM_PORT, ['uv', 'run', 'python', '-m', 'ops_platform'], platformDir, platformEnv, `http://127.0.0.1:${PLATFORM_PORT}/.well-known/jwks.json`, 90_000);
      Object.assign(signIn, { NEXT_PUBLIC_AUTH_PROVIDER: 'platform', NEXT_PUBLIC_OPS_PLATFORM_API_URL: `http://127.0.0.1:${PLATFORM_PORT}` });
    }
    consoleProc = await serve(
      'console',
      CONSOLE_PORT,
      ['pnpm', 'exec', 'next', 'dev', '-p', String(CONSOLE_PORT)],
      join(ROOT, 'apps/console'),
      {
        ...env,
        NEXT_PUBLIC_OPS_CHAT_API_URL: `http://127.0.0.1:${AGENTS_PORT}`,
        NEXT_PUBLIC_OPS_CASES_API_URL: `http://127.0.0.1:${AGENTS_PORT}`,
        NEXT_PUBLIC_OPS_REGISTRY_API_URL: `http://127.0.0.1:${AGENTS_PORT}`,
        ...signIn,
        ...toolsUrl,
        // Next locks its build directory and refuses a second server on it, so each run (its own console port) gets
        // its own, clear of `make up`'s console and of another session's run.
        OPS_CONSOLE_DIST_DIR: CONSOLE_DIST_DIR,
      },
      `${consoleUrl}/`,
      180_000,
    );
    return await body(consoleUrl, stack);
  } finally {
    if (consoleProc) {
      // The Next server (a child of pnpm) writes its build directory until it exits, after pnpm does; removing the
      // directory sooner leaves it recreated. It holds the console port until then.
      stop(consoleProc);
      for (let i = 0; i < 40 && (await portBusy(CONSOLE_PORT)); i++) await new Promise((r) => setTimeout(r, 250));
      await new Promise((r) => setTimeout(r, 500));
    }
    // Cleanup never fails a run: a straggling write can still race the delete, which then leaves the folder behind.
    try {
      rmSync(join(ROOT, 'apps/console', CONSOLE_DIST_DIR), { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
    } catch {
      // left for the next run's cleanup or a manual remove
    }
    if (platformProc) stop(platformProc);
    if (toolsProc) stop(toolsProc);
    opa?.stop();
    if (bankProc) {
      bankProc.stdin?.end();
      stop(bankProc);
    }
    stop(agents);
  }
}
