// What a Node use case script (the ui layer) shares with the Python harness in docs/usecases/lib: PASS/FAIL checks,
// and services started fresh on the use-case ports. The ui stack is the agents service on the scripted model plus a
// console dev server whose chat points at it, so a browser test never reaches a model provider or another session's
// console.
import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, openSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { networkInterfaces, tmpdir } from 'node:os';
import { createConnection } from 'node:net';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ensureConsoleBuild, materializeConsoleBuild } from './console-build.ts';

export { chromium } from 'playwright';

/** The tree the runner was invoked from (OPS_USECASE_ROOT, set by the runner), else the one this package sits in. */
export const ROOT = process.env.OPS_USECASE_ROOT ?? resolve(fileURLToPath(new URL('.', import.meta.url)), '../../..');
/**
 * Where a use case keeps its screenshots and logs for a card (`card` is its number, `parts` any subfolder), not created
 * here. OPS_EVIDENCE_DIR when set; else the maintainers' card store when this checkout has one, so a card's proof sits
 * with the card; else a folder under the system temp directory.
 */
export function evidenceDir(card: string, ...parts: string[]): string {
  const store = join(ROOT, '.codeloop', 'evidence');
  const base = process.env.OPS_EVIDENCE_DIR ?? (existsSync(store) ? store : join(tmpdir(), 'ops-ai-evidence'));
  return join(base, card, ...parts);
}
export const AGENTS_PORT = Number(process.env.OPS_USECASE_AGENTS_PORT ?? 8790);
export const CONSOLE_PORT = Number(process.env.OPS_USECASE_CONSOLE_PORT ?? 3018);
/** The embed app (apps/embed, c-158), started when a use case asks for `embed`. */
export const EMBED_PORT = Number(process.env.OPS_USECASE_EMBED_PORT ?? 3019);
export const PLATFORM_PORT = Number(process.env.OPS_USECASE_PLATFORM_PORT ?? 8810);
const PLATFORM_INTERNAL_PORT = Number(process.env.OPS_USECASE_PLATFORM_INTERNAL_PORT ?? 8811);
export const TOOLS_PORT = Number(process.env.OPS_USECASE_TOOLS_PORT ?? 8792);
export const KB_PORT = Number(process.env.OPS_USECASE_KB_PORT ?? 8793);
export const FILES_PORT = Number(process.env.OPS_USECASE_FILES_PORT ?? 8796);
/** documents-service (c-256): extractions and document types, reading bytes from files-service. */
export const DOCUMENTS_PORT = Number(process.env.OPS_USECASE_DOCUMENTS_PORT ?? 8798);
export const MODELS_PORT = Number(process.env.OPS_USECASE_MODELS_PORT ?? 8794);
export const IDP_PORT = Number(process.env.OPS_USECASE_IDP_PORT ?? 8797);
export const RUNNER_PORT = Number(process.env.OPS_USECASE_RUNNER_PORT ?? 8789);
/** The OIDC client secret name a `signIn` stack's platform-service holds. */
export const SIGNIN_SECRET = 'uc-oidc';
const FAKE_OPENAI_PORT = Number(process.env.OPS_USECASE_FAKE_OPENAI_PORT ?? 8795);
/** The committed fake-OpenAI rules (the levy's and the demo's); services/models-service/scripts/fake_openai reads `<folder>/script.json`. */
const DEMO_RULES = 'services/models-service/seed/demo-fake-openai';
/** platform-service's dev seed: the demo's builder and Security approver, and the dev password. */
const JAMES = 'j.richardson@harborpine.example';
const NADIA = 'n.petrov@harborpine.example';
// The Security team's admin: only they change egress and secrets (c-079).
const SAM = 's.adeyemi@harborpine.example';
const DEMO_PASSWORD = 'northfield-demo';
const CONSOLE_DIST_DIR = `node_modules/.cache/next-usecase-${CONSOLE_PORT}`;
// The run's own tsconfig, beside its build directory, relative to apps/console.
const CONSOLE_TSCONFIG = `node_modules/.cache/tsconfig-usecase-${CONSOLE_PORT}.json`;
const EMBED_DIST_DIR = `node_modules/.cache/next-usecase-${EMBED_PORT}`;
const EMBED_TSCONFIG = `node_modules/.cache/tsconfig-usecase-${EMBED_PORT}.json`;

/** Writes the run's tsconfig: the console's, extended, with its includes rebased so they mean the same files. Next adds
 * the build directory's type globs to this file instead of to the committed one. */
function writeRunTsconfig(app = 'apps/console', file = CONSOLE_TSCONFIG): void {
  const appDir = join(ROOT, app);
  const committed = JSON.parse(readFileSync(join(appDir, 'tsconfig.json'), 'utf8')) as { include?: string[] };
  const up = '../../';
  const config = { extends: `${up}tsconfig.json`, include: (committed.include ?? []).map((p) => `${up}${p}`) };
  mkdirSync(join(appDir, 'node_modules/.cache'), { recursive: true });
  writeFileSync(join(appDir, file), `${JSON.stringify(config, null, 2)}\n`);
}
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

/**
 * Approves a tool module's open review in agents-service's Reviews as `headers` (a Security approver), as Human
 * Tasks would (c-163); Reviews applies it in tools-service. The module is read as `owner`, a person of its own team:
 * the approver acts in Security, which does not read another team's modules (c-509). Returns the module's detail
 * afterwards.
 */
export async function approveToolReview(moduleId: string, headers: Record<string, string>, owner: Record<string, string>): Promise<Record<string, unknown>> {
  const tools = `http://127.0.0.1:${TOOLS_PORT}/v1/tool-modules/${moduleId}`;
  const read = async () => ((await (await fetch(tools, { headers: owner })).json()) as { data: Record<string, any> }).data;
  const waiting = (await read()).versions.find((v: { status: string }) => v.status === 'in_review');
  if (!waiting?.reviewId) throw new Error(`${moduleId} has no version waiting for review`);
  const r = await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/publish-requests/${waiting.reviewId}/decision`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision: 'approved' }),
  });
  if (!r.ok) throw new Error(`approving ${waiting.reviewId}: ${r.status} ${await r.text()}`);
  return read();
}

/**
 * Proves each unverified domain of a saved sign-in provider as a bank would (c-195): publishes the claim's TXT record
 * at the fake identity provider's DNS and asks platform-service to verify it. Throws on any refusal.
 */
export async function proveDomains(provider: { verification?: { domain: string; verifiedAt: string | null; record: { value: string } }[] }, headers: Record<string, string>): Promise<void> {
  for (const c of provider.verification ?? []) {
    if (c.verifiedAt) continue;
    const put = await fetch(`http://127.0.0.1:${IDP_PORT}/dns/txt/${c.domain}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ values: [c.record.value] }) });
    const v = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/settings/sign-in/domains/${c.domain}/verify`, { method: 'POST', headers });
    if (!put.ok || !v.ok) throw new Error(`verifying ${c.domain}: ${put.status} ${v.status} ${await v.text()}`);
  }
}

/** The password every person a use case invites sets when accepting (c-218). */
export const INVITED_PASSWORD = "an invited person's password";

/**
 * A person made the way a bank makes one (c-218): `adminEmail`, signed in with the demo password, invites `email`
 * with `role` into `team` on platform-service, and the person accepts with a name and INVITED_PASSWORD. Returns the
 * person's session token. Throws on any refusal, so a script never checks a person who was not made.
 */
export async function invitePerson(adminEmail: string, email: string, role: string, team = 'team_ops'): Promise<string> {
  const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
  const json = { 'Content-Type': 'application/json' };
  const signIn = (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: json, body: JSON.stringify({ email: adminEmail, password: 'northfield-demo' }) })).json()) as { data?: { token?: string } };
  const headers = { ...json, Authorization: `Bearer ${signIn.data?.token}`, 'X-Team-Id': team };
  const invited = (await (await fetch(`${platform}/v1/settings/members/invite`, { method: 'POST', headers, body: JSON.stringify({ emails: [email], role }) })).json()) as { data?: { invites?: { token?: string }[] } };
  const token = invited.data?.invites?.[0]?.token;
  if (!token) throw new Error(`inviting ${email} as ${role}: ${JSON.stringify(invited).slice(0, 300)}`);
  const name = email.split('@')[0].replace(/\./g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  const accepted = (await (await fetch(`${platform}/v1/invites/${token}/accept`, { method: 'POST', headers: json, body: JSON.stringify({ name, password: INVITED_PASSWORD }) })).json()) as { data?: { token?: string } };
  if (!accepted.data?.token) throw new Error(`accepting ${email}: ${JSON.stringify(accepted).slice(0, 300)}`);
  return accepted.data.token;
}

/** Signs `email` in on the console's login page in a fresh browser context and returns the page. */
export async function consoleSignIn(browser: import('playwright').Browser, consoleUrl: string, email: string, password: string, errors: string[]): Promise<import('playwright').Page> {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
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
  /** Settings for platform-service when `platform` is on, e.g. `{ OPS_TEAM_DELETE_AFTER_DAYS: '0' }` (c-529). */
  platformEnv?: Record<string, string>;
  /**
   * Also start platform-service on the run's database (its own migration chain, the dev seed of team_ops with Priya,
   * James and Maya) and sign the console in through it, so every call carries a person's token.
   */
  platform?: boolean;
  /**
   * Also start tools-service on the run's database (its migration chain and dev seed), deciding with a private OPA,
   * and point the console's Tools pages at it. `bank` adds the https fake bank on this machine's private address
   * (docs/usecases/lib/fake_bank_https.py), which tools-service reaches as `https://api.bank.test`; `'core'` serves the
   * core-banking system there instead (services/tools-service/scripts/fake_bank: customers, accounts, holds, statements).
   */
  tools?: {
    bank?: boolean | 'core';
    /** Point the agents service at this tools-service as its gateway, so agents are granted and call its operations. */
    gateway?: boolean;
    /**
     * Let tools-service reach compose's GreenMail as `mail.harborpine.test` (IMAP) and Mailpit as
     * `smtp.harborpine.test` (SMTP), dialled on this machine's private address; the use case still puts both hosts and
     * `stack.mail.range` on the tenant's allow-list, as a person would.
     */
    mail?: boolean;
    /** Start runner-service (c-531) beside tools-service, so a code operation runs its Python on WASM. */
    runner?: boolean;
  };
  /**
   * The banker demo on the run's own stack: platform sign-in, tools-service with the fake bank as the agents'
   * gateway, models-service answering through the fake OpenAI with the committed demo rules, the demo knowledge
   * seeded into kb-service with its agents wired (services/kb-service/scripts/seed_demo_knowledge.py), and the bank
   * module reimported with its hold approved (services/tools-service/scripts/reimport_bank_module.py).
   */
  demo?: boolean;
  /**
   * With `demo`: another committed fake-OpenAI rules folder (repo-relative, holding script.json) instead of the demo's,
   * for a use case whose model calls the demo does not answer (documents' Detect, say).
   */
  fakeModelRules?: string;
  /** Also start the embed app (apps/embed) on its own port, its `/v1` and loader routed to the run's agents service. */
  embed?: boolean;
  /**
   * With `platform`: also start the local fake identity provider (`python -m ops_signin.fake_idp`) on the IdP port and
   * set platform-service up for sign-in providers (its public and the console's URLs, the OIDC client secret
   * `uc-oidc`, reset mail written to a folder), so a use case can configure OIDC or SAML and sign in through them.
   */
  signIn?: boolean;
}

/** What the stack started, for a use case to drive: the fake bank's host and the private range it serves on. */
export interface Stack {
  /** The fake identity provider's origin and the folder reset mail is written to, when `signIn` started them. */
  idpUrl?: string;
  mailDir?: string;
  /** With `tools.bank`: the bank's host name, the range it answers on, its own address for reading what it
   * received (`${url}/webhooks.json`, the webhook stand-in), and the CA file its certificate for `host` is signed by. */
  bank?: { host: string; range: string; url: string; ca: string };
  /** With `tools.mail`: the names tools-service resolves to GreenMail and Mailpit, and the range they answer on. */
  mail?: { imapHost: string; smtpHost: string; range: string };
  /** The embed app's origin when the stack started it: the Ops AI host a bank page loads the loader from. */
  embedUrl?: string;
  /**
   * Starts a workflow runner worker (`python -m ops_agents.api.worker`) on the run's database with the agents service's
   * settings plus `env` (e.g. OPS_ENGINE_FAULT_KILL_AFTER_NODE); resolves once it logs that it started. A run started
   * with none waits in the queue. Every worker still running stops with the stack.
   */
  startWorker(env?: Record<string, string>): Promise<EngineWorker>;
}

export interface EngineWorker {
  /** SIGTERM, then waits for it to exit. */
  stop(): Promise<void>;
  /** The process's exit code once it ends, whether stopped or killed by a fault setting. */
  exited: Promise<number | null>;
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
/** This machine's private IPv4 address: egress refuses loopback, and compose publishes its ports on every address. */
function privateAddress(): string {
  for (const nets of Object.values(networkInterfaces())) {
    for (const net of nets ?? []) {
      if (net.family === 'IPv4' && !net.internal && /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(net.address)) return net.address;
    }
  }
  throw new Error('no private IPv4 address: tools-service refuses loopback, so GreenMail and Mailpit cannot be reached');
}

function startBank(app: 'statements' | 'core' = 'statements'): Promise<{ info: { settings: Record<string, string>; range: string; host: string }; child: ChildProcess }> {
  const env = { ...stackEnv(process.env), PYTHONPATH: [join(ROOT, 'docs/usecases/lib'), process.env.PYTHONPATH].filter(Boolean).join(':') };
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_bank_serve.py')], { env: app === 'core' ? { ...env, OPS_FAKE_BANK_APP: 'core' } : env, stdio: ['pipe', 'pipe', 'inherit'], detached: true });
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

/** The services' environment: the caller's, without model keys, the shared stack's models-service and
 * platform-service routes (scripted model only) or a stray venv, plus `extra`. The shared .env's OPS_MODELS_URL would
 * send a run's agents to the shared stack's models-service and its fake OpenAI instead of the scripted model; an
 * inherited OPS_PLATFORM_URL makes a run without platform-service build policy readers that fail closed. A run that
 * wants either passes it in `extra`. */
export function stackEnv(base: NodeJS.ProcessEnv, extra: Record<string, string> = {}): NodeJS.ProcessEnv {
  const inherited = { ...base };
  for (const key of ['OPS_MODELS_URL', 'OPS_MODELS_KEY', 'OPS_MODELS_FAKE_OPENAI_URL', 'OPS_PLATFORM_URL']) delete inherited[key];
  const env = { ...inherited, ...extra };
  for (const key of ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'VIRTUAL_ENV']) delete env[key];
  return env;
}

/** The agents service on the scripted model plus a console whose chat calls it. Stops both when `body` returns. */
export async function withUiStack<T>(body: (consoleUrl: string, stack: Stack) => Promise<T>, given: StackOptions = {}): Promise<T> {
  const options: StackOptions = given.demo ? { ...given, platform: true, tools: { ...given.tools, bank: true, gateway: true } } : given;
  const env = stackEnv(process.env);
  const consoleUrl = `http://localhost:${CONSOLE_PORT}`;
  const runDb = `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`;
  let fakeOpenAi: ChildProcess | undefined;
  let modelsProc: ChildProcess | undefined;
  const modelsRoute: Record<string, string> = {};
  if (options.demo) {
    // Turns run through models-service on the fake OpenAI, so the agents service needs both before it starts. The
    // run's database is created by the agents service's migrate step; models-service adds its own chain beside it.
    const agentsDir = join(ROOT, 'services/agents-service');
    await runToEnd('agents-migrate', ['uv', 'run', 'python', 'scripts/scripted_server.py', '--port', '0', '--db', DB, '--migrate-only'], agentsDir, env);
    fakeOpenAi = await serve('fake-openai', FAKE_OPENAI_PORT, ['uv', 'run', '--project', '..', 'python', '-m', 'fake_openai', join(ROOT, options.fakeModelRules ?? DEMO_RULES)], join(ROOT, 'services/models-service/scripts'), stackEnv(process.env, { FAKE_OPENAI_PORT: String(FAKE_OPENAI_PORT) }), `http://127.0.0.1:${FAKE_OPENAI_PORT}/v1/models`, 60_000);
    const modelsDir = join(ROOT, 'services/models-service');
    const modelsEnv = stackEnv(process.env, { OPS_DATABASE_URL: runDb, OPS_MODELS_PORT: String(MODELS_PORT), OPS_MODELS_FAKE_OPENAI_URL: `http://127.0.0.1:${FAKE_OPENAI_PORT}/v1` });
    await runToEnd('models-migrate', ['uv', 'run', 'alembic', 'upgrade', 'head'], modelsDir, modelsEnv);
    modelsProc = await serve('models', MODELS_PORT, ['uv', 'run', 'python', '-m', 'ops_models'], modelsDir, modelsEnv, `http://127.0.0.1:${MODELS_PORT}/health`, 90_000);
    // models-service's dev seed: agents-service's own key.
    Object.assign(modelsRoute, { OPS_MODELS_URL: `http://127.0.0.1:${MODELS_PORT}`, OPS_MODELS_KEY: 'mk_dev_agents' });
    // The demo's agents (ag_advisor, ag_policy, ag_levy beside the fixtures'), as the shared stack seeds them.
    modelsRoute.OPS_AGENTS_SEED_FILE = 'seed/chat_agents.json';
  }
  let agentsEnv: NodeJS.ProcessEnv = {};
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
    (agentsEnv = stackEnv(process.env, {
      ...(options.platform ? { OPS_AUTH_MODE: 'platform', OPS_PLATFORM_URL: `http://127.0.0.1:${PLATFORM_PORT}`, OPS_PLATFORM_INTERNAL_PORT: String(PLATFORM_INTERNAL_PORT) } : {}),
      // kb-service starts below on its known port; agents ask it on first use. Without it agents that hold knowledge
      // bases are refused, so every ui stack has one.
      OPS_KB_URL: `http://127.0.0.1:${KB_PORT}`,
      // Tool module reviews decided in Reviews are applied in tools-service (c-163), with or without a gateway.
      OPS_TOOLS_URL: `http://127.0.0.1:${TOOLS_PORT}`,
      // documents-service starts below; a workflow save pins its document types there and a worker's Extract from
      // file step reads through it (c-256). Workers inherit this environment.
      OPS_DOCUMENTS_URL: `http://127.0.0.1:${DOCUMENTS_PORT}`,
      ...modelsRoute,
      // The embed app's origin is configuration: agents-service trusts no request header to name it (c-158).
      // The console's origin too: a preview session (c-232) is minted for the console's own frame.
      ...(options.embed
        ? { OPS_EMBED_ORIGINS: JSON.stringify([`http://localhost:${EMBED_PORT}`]), OPS_CONSOLE_URL: consoleUrl }
        : {}),
      ...options.agentsEnv,
    })),
    `http://127.0.0.1:${AGENTS_PORT}/health`,
    90_000,
  );
  let consoleProc: ChildProcess | undefined;
  let embedProc: ChildProcess | undefined;
  let embedTsconfig: string | undefined;
  let committedTsconfig: string | undefined;
  let platformProc: ChildProcess | undefined;
  let idpProc: ChildProcess | undefined;
  let toolsProc: ChildProcess | undefined;
  let runnerProc: ChildProcess | undefined;
  let kbProc: ChildProcess | undefined;
  let filesProc: ChildProcess | undefined;
  let documentsProc: ChildProcess | undefined;
  const filesDir = mkdtempSync(join(tmpdir(), 'usecase-files-'));
  let bankProc: ChildProcess | undefined;
  let opa: { url: string; stop: () => void } | undefined;
  const workers: ChildProcess[] = [];
  const stack: Stack = {
    startWorker: async (extra = {}) => {
      mkdirSync(LOG_DIR, { recursive: true });
      const logPath = join(LOG_DIR, `worker-${AGENTS_PORT}-${workers.length + 1}.log`);
      const log = openSync(logPath, 'a');
      const env = {
        ...agentsEnv,
        OPS_DATABASE_URL: `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`,
        OPS_ENGINE_POLL_SECONDS: '0.2',
        // The stack's files-service: the Email received trigger stores attachments there, and without it (or the
        // gateway) the worker leaves mailboxes unread.
        OPS_FILES_URL: `http://127.0.0.1:${FILES_PORT}`,
        ...(options.tools?.gateway ? { OPS_GATEWAY_URL: `http://127.0.0.1:${TOOLS_PORT}` } : {}),
        ...extra,
      };
      const start = readFileSync(logPath, 'utf8').length;
      const child = spawn('uv', ['run', 'python', '-m', 'ops_agents.api.worker'], { cwd: join(ROOT, 'services/agents-service'), env, stdio: ['ignore', log, log], detached: true });
      workers.push(child);
      const exited = new Promise<number | null>((done) => child.on('exit', (code) => done(code)));
      for (let i = 0; i < 240 && !readFileSync(logPath, 'utf8').slice(start).includes('engine_worker_started'); i++) {
        if (child.exitCode !== null) throw new Error(`worker exited with ${child.exitCode} before it started; see ${logPath}`);
        await new Promise((r) => setTimeout(r, 250));
      }
      return {
        exited,
        stop: async () => {
          stop(child);
          await Promise.race([exited, new Promise((r) => setTimeout(r, 10_000))]);
        },
      };
    },
  };
  try {
    const signIn: Record<string, string> = {};
    const toolsUrl: Record<string, string> = {};
    if (options.tools) {
      const toolsDir = join(ROOT, 'services/tools-service');
      const bankSettings: Record<string, string> = {};
      if (options.tools.bank) {
        // The demo's bank is the core-banking system (customers, accounts, holds); the default is the Statements API.
        const bank = await startBank(options.demo || options.tools.bank === 'core' ? 'core' : 'statements');
        bankProc = bank.child;
        Object.assign(bankSettings, bank.info.settings);
        const dialled = (JSON.parse(bank.info.settings.OPS_EGRESS_RESOLVE ?? '{}') as Record<string, string>)[bank.info.host];
        stack.bank = { host: bank.info.host, range: bank.info.range, url: `https://${dialled ?? bank.info.host}`, ca: bank.info.settings.OPS_EGRESS_CA_FILE ?? '' };
      }
      if (options.tools.mail) {
        const here = privateAddress();
        const resolve = JSON.parse(bankSettings.OPS_EGRESS_RESOLVE ?? '{}') as Record<string, string>;
        resolve['mail.harborpine.test'] = `${here}:${process.env.OPS_GREENMAIL_IMAP_PORT ?? 3143}`;
        resolve['smtp.harborpine.test'] = `${here}:${process.env.OPS_MAILPIT_SMTP_PORT ?? 1025}`;
        bankSettings.OPS_EGRESS_RESOLVE = JSON.stringify(resolve);
        stack.mail = { imapHost: 'mail.harborpine.test', smtpHost: 'smtp.harborpine.test', range: `${here}/32` };
      }
      opa = await startOpa();
      const toolsEnv = stackEnv(process.env, {
        OPS_DATABASE_URL: `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`,
        OPS_GATEWAY_PORT: String(TOOLS_PORT),
        OPS_OPA_URL: opa.url,
        OPS_CORS_ORIGINS: JSON.stringify([consoleUrl]),
        // Workflow approvals name agents-service's workflows (c-039); without this tools-service would ask the dev port.
        OPS_AGENTS_URL: `http://127.0.0.1:${AGENTS_PORT}`,
        // send_reply sends through the provider settings pick and fails with none (c-187): the dev fake writes each
        // mail to this run's folder.
        OPS_MAIL_PROVIDER: 'fake',
        OPS_MAIL_FROM: 'ops@harborpine.example',
        OPS_MAIL_FAKE_OUT_DIR: mkdtempSync(join(tmpdir(), 'usecase-mail-out-')),
        // Under platform sign-in tools-service verifies the console's tokens too, so people are told apart by role.
        ...(options.platform ? { OPS_AUTH_MODE: 'platform', OPS_PLATFORM_URL: `http://127.0.0.1:${PLATFORM_PORT}`, OPS_PLATFORM_INTERNAL_PORT: String(PLATFORM_INTERNAL_PORT) } : {}),
        ...bankSettings,
        ...(options.tools.runner ? { OPS_RUNNER_URL: `http://127.0.0.1:${RUNNER_PORT}` } : {}),
      });
      if (options.tools.runner) {
        // The runner calls back to this run's tools-service for each bound call; the pinned Python build is fetched once.
        const runnerDir = join(ROOT, 'services/runner-service');
        const runnerEnv = stackEnv(process.env, { OPS_RUNNER_PORT: String(RUNNER_PORT), OPS_TOOLS_URL: `http://127.0.0.1:${TOOLS_PORT}` });
        await runToEnd('runner-fetch', ['uv', 'run', 'python', '-m', 'ops_runner.fetch'], runnerDir, runnerEnv);
        runnerProc = await serve('runner', RUNNER_PORT, ['uv', 'run', 'python', '-m', 'ops_runner'], runnerDir, runnerEnv, `http://127.0.0.1:${RUNNER_PORT}/health`, 90_000);
      }
      await runToEnd('tools-migrate', ['uv', 'run', 'alembic', 'upgrade', 'head'], toolsDir, toolsEnv);
      toolsProc = await serve('tools', TOOLS_PORT, ['uv', 'run', 'python', '-m', 'ops_tools'], toolsDir, toolsEnv, `http://127.0.0.1:${TOOLS_PORT}/health`, 90_000);
      toolsUrl.NEXT_PUBLIC_OPS_TOOLS_API_URL = `http://127.0.0.1:${TOOLS_PORT}`;
    }
    if (options.platform && options.signIn) {
      // The fake DNS answers on the same port number over UDP, so a domain's TXT record can be proven (c-195).
      idpProc = await serve('fake-idp', IDP_PORT, ['uv', 'run', 'python', '-m', 'ops_signin.fake_idp', '--port', String(IDP_PORT), '--dns-port', String(IDP_PORT)], ROOT, env, `http://127.0.0.1:${IDP_PORT}/health`, 60_000);
      stack.idpUrl = `http://127.0.0.1:${IDP_PORT}`;
      stack.mailDir = mkdtempSync(join(tmpdir(), 'usecase-mail-'));
    }
    if (options.platform) {
      const platformDir = join(ROOT, 'services/platform-service');
      // The agents service created the run's database on start; platform-service adds its own tables beside them.
      const platformEnv = stackEnv(process.env, {
        OPS_DATABASE_URL: `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`,
        OPS_PLATFORM_PORT: String(PLATFORM_PORT),
        OPS_PLATFORM_INTERNAL_PORT: String(PLATFORM_INTERNAL_PORT),
        // The seed's own roles: use cases check what a builder or viewer may not do, so nobody is Admin everywhere.
        OPS_SEED_EVERYONE_ADMIN: 'false',
        OPS_CORS_ORIGINS: JSON.stringify([consoleUrl]),
        // What still runs in a team, read before a team is deleted or the workspace closed (c-529).
        OPS_AGENTS_URL: `http://127.0.0.1:${AGENTS_PORT}`,
        ...(stack.mailDir
          ? {
              OPS_PLATFORM_PUBLIC_URL: `http://127.0.0.1:${PLATFORM_PORT}`,
              OPS_CONSOLE_URL: consoleUrl,
              OPS_SIGNIN_SECRETS: JSON.stringify({ [SIGNIN_SECRET]: 'uc-oidc-secret' }),
              OPS_SIGNIN_DNS_SERVERS: JSON.stringify([`127.0.0.1:${IDP_PORT}`]),
              OPS_MAIL_PROVIDER: 'fake',
              OPS_MAIL_FROM: 'ops@harborpine.example',
              OPS_MAIL_FAKE_OUT_DIR: stack.mailDir,
            }
          : {}),
        ...options.platformEnv,
      });
      await runToEnd('platform-migrate', ['uv', 'run', 'alembic', 'upgrade', 'head'], platformDir, platformEnv);
      // Dev mode seeds on start. The public app has no /health; the key set answers once it serves.
      platformProc = await serve('platform', PLATFORM_PORT, ['uv', 'run', 'python', '-m', 'ops_platform'], platformDir, platformEnv, `http://127.0.0.1:${PLATFORM_PORT}/.well-known/jwks.json`, 90_000);
      Object.assign(signIn, { NEXT_PUBLIC_AUTH_PROVIDER: 'platform', NEXT_PUBLIC_OPS_PLATFORM_API_URL: `http://127.0.0.1:${PLATFORM_PORT}` });
    }
    // files-service on the run's database: kb-service stores every upload there, as on the shared stack (c-094).
    // Scanning is off, as the owner decided for now; the hook stays for when a scanner is chosen.
    const auth: Record<string, string> = options.platform ? { OPS_AUTH_MODE: 'platform', OPS_PLATFORM_URL: `http://127.0.0.1:${PLATFORM_PORT}`, OPS_PLATFORM_INTERNAL_PORT: String(PLATFORM_INTERNAL_PORT) } : {};
    const filesSvcDir = join(ROOT, 'services/files-service');
    const filesEnv = stackEnv(process.env, {
      OPS_DATABASE_URL: `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`,
      OPS_FILES_PORT: String(FILES_PORT),
      OPS_FILES_DIR: filesDir,
      OPS_FILES_SCANNING: 'off',
      // Service events (file.deleted, file.read_requested) reach this run's agents-service (c-250).
      OPS_AGENTS_URL: `http://127.0.0.1:${AGENTS_PORT}`,
      // The console calls files-service for its Storage settings (c-100).
      OPS_CORS_ORIGINS: JSON.stringify([consoleUrl]),
      ...auth,
    });
    await runToEnd('files-migrate', ['uv', 'run', 'alembic', 'upgrade', 'head'], filesSvcDir, filesEnv);
    filesProc = await serve('files', FILES_PORT, ['uv', 'run', 'python', '-m', 'ops_files'], filesSvcDir, filesEnv, `http://127.0.0.1:${FILES_PORT}/health`, 90_000);
    // documents-service on the run's database, after files' chain (files_0006 drops the tables documents_0001 makes).
    const documentsDir = join(ROOT, 'services/documents-service');
    const documentsEnv = stackEnv(process.env, {
      OPS_DATABASE_URL: `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`,
      OPS_DOCUMENTS_PORT: String(DOCUMENTS_PORT),
      OPS_FILES_URL: `http://127.0.0.1:${FILES_PORT}`,
      OPS_CORS_ORIGINS: JSON.stringify([consoleUrl]),
      ...auth,
      // Extractions run on the run's models-service with documents-service's own dev key (c-235, c-256).
      ...(modelsRoute.OPS_MODELS_URL ? { OPS_MODELS_URL: modelsRoute.OPS_MODELS_URL, OPS_MODELS_KEY: 'mk_dev_extract' } : {}),
    });
    await runToEnd('documents-migrate', ['uv', 'run', 'alembic', 'upgrade', 'head'], documentsDir, documentsEnv);
    documentsProc = await serve('documents', DOCUMENTS_PORT, ['uv', 'run', 'python', '-m', 'ops_documents'], documentsDir, documentsEnv, `http://127.0.0.1:${DOCUMENTS_PORT}/health`, 90_000);
    // kb-service on the run's database, holding the agents fixtures' knowledge under the ids the seeded agents were
    // granted (docs/usecases/lib/seed_fixture_knowledge.py, through kb-service's API).
    const kbDir = join(ROOT, 'services/kb-service');
    const kbEnv = stackEnv(process.env, {
      OPS_DATABASE_URL: `postgresql+asyncpg://ops:ops@localhost:${process.env.OPS_PG_PORT ?? 5477}/${DB}`,
      OPS_KB_PORT: String(KB_PORT),
      OPS_FILES_URL: `http://127.0.0.1:${FILES_PORT}`,
      // A knowledge base's "used by" comes from agents-service (c-072 T007), on this run's port.
      OPS_AGENTS_URL: `http://127.0.0.1:${AGENTS_PORT}`,
      OPS_CORS_ORIGINS: JSON.stringify([consoleUrl]),
      ...auth,
    });
    await runToEnd('kb-migrate', ['uv', 'run', 'alembic', 'upgrade', 'head'], kbDir, kbEnv);
    kbProc = await serve('kb', KB_PORT, ['uv', 'run', 'python', '-m', 'ops_kb'], kbDir, kbEnv, `http://127.0.0.1:${KB_PORT}/health`, 90_000);
    const seedArgs = ['--kb', `http://127.0.0.1:${KB_PORT}`, '--files', `http://127.0.0.1:${FILES_PORT}`, ...(options.platform ? ['--platform', `http://127.0.0.1:${PLATFORM_PORT}`] : [])];
    await runToEnd('kb-seed', ['uv', 'run', 'python', join(ROOT, 'docs/usecases/lib/seed_fixture_knowledge.py'), ...seedArgs], ROOT, env);
    // The demo's document types (levy_notice v1 and its samples), which the seeded levy workflows name (c-236).
    const typeArgs = options.platform ? ['--platform', `http://127.0.0.1:${PLATFORM_PORT}`] : ['--dev'];
    await runToEnd('document-types', ['uv', 'run', 'python', 'scripts/seed_document_types.py', '--documents', `http://127.0.0.1:${DOCUMENTS_PORT}`, '--files', `http://127.0.0.1:${FILES_PORT}`, ...typeArgs], documentsDir, stackEnv(process.env, { OPS_PLATFORM_DEMO_PASSWORD: DEMO_PASSWORD }));
    if (options.demo) {
      const demoEnv = stackEnv(process.env, { OPS_PLATFORM_DEMO_PASSWORD: DEMO_PASSWORD });
      // The Security admin allows the fake bank's host and the private range it serves on, as the demo's set-up does.
      const signIn = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: SAM, password: DEMO_PASSWORD }) });
      const admin = { Authorization: `Bearer ${((await signIn.json()) as { data: { token: string } }).data.token}`, 'Content-Type': 'application/json' };
      for (const [path, value] of [['hosts', stack.bank!.host], ['ranges', stack.bank!.range]] as const) {
        const r = await fetch(`http://127.0.0.1:${TOOLS_PORT}/v1/egress/${path}`, { method: 'POST', headers: admin, body: JSON.stringify({ value, note: 'demo stack' }) });
        // 200 is tools-service's answer when the value is allowed already (`changed: false`).
        if (![200, 201, 409].includes(r.status)) throw new Error(`egress ${path} ${value}: ${r.status} ${await r.text()}`);
      }
      // The bank reads first: the demo seed grants ag_advisor operations the reimport publishes.
      await runToEnd('demo-bank-module', ['uv', 'run', 'python', 'scripts/reimport_bank_module.py', '--tools', `http://127.0.0.1:${TOOLS_PORT}`, '--platform', `http://127.0.0.1:${PLATFORM_PORT}`, '--agents', `http://127.0.0.1:${AGENTS_PORT}`, '--as', JAMES, '--decide-as', NADIA], join(ROOT, 'services/tools-service'), demoEnv);
      await runToEnd('demo-knowledge', ['uv', 'run', 'python', 'scripts/seed_demo_knowledge.py', '--kb', `http://127.0.0.1:${KB_PORT}`, '--files', `http://127.0.0.1:${FILES_PORT}`, '--platform', `http://127.0.0.1:${PLATFORM_PORT}`, '--agents', `http://127.0.0.1:${AGENTS_PORT}`], kbDir, demoEnv);
    }
    committedTsconfig = readFileSync(join(ROOT, 'apps/console/tsconfig.json'), 'utf8');
    const publicEnv: Record<string, string> = {
      NEXT_PUBLIC_OPS_CHAT_API_URL: `http://127.0.0.1:${AGENTS_PORT}`,
      NEXT_PUBLIC_OPS_CASES_API_URL: `http://127.0.0.1:${AGENTS_PORT}`,
      NEXT_PUBLIC_OPS_REGISTRY_API_URL: `http://127.0.0.1:${AGENTS_PORT}`,
      ...signIn,
      ...toolsUrl,
      // The console appends /v1 itself.
      NEXT_PUBLIC_OPS_KNOWLEDGE_API_URL: `http://127.0.0.1:${KB_PORT}`,
      NEXT_PUBLIC_OPS_FILES_API_URL: `http://127.0.0.1:${FILES_PORT}`,
      NEXT_PUBLIC_OPS_DOCUMENTS_API_URL: `http://127.0.0.1:${DOCUMENTS_PORT}`,
      // The embed app the console's Preview frame loads, when the stack starts one.
      ...(options.embed ? { NEXT_PUBLIC_OPS_EMBED_URL: `http://localhost:${EMBED_PORT}` } : {}),
    };
    // Production build by default: built once per source hash and stack shape, then a copy per run (console-build.ts).
    // OPS_USECASE_CONSOLE=dev keeps `next dev`, for a run that needs hot reload or a page the build omits.
    const dev = process.env.OPS_USECASE_CONSOLE === 'dev';
    let consoleArgv = ['pnpm', 'exec', 'next', 'dev', '-p', String(CONSOLE_PORT)];
    const consoleEnv: NodeJS.ProcessEnv = { ...env, ...publicEnv };
    if (dev) {
      writeRunTsconfig();
    } else {
      const build = await ensureConsoleBuild(ROOT, publicEnv, env, LOG_DIR);
      materializeConsoleBuild(ROOT, build, CONSOLE_DIST_DIR, publicEnv);
      consoleArgv = ['pnpm', 'exec', 'next', 'start', '-p', String(CONSOLE_PORT)];
      // The dev-only pages (/dev, /preview) answer 404 on a production server unless this is set; no deployment sets it.
      Object.assign(consoleEnv, { OPS_ALLOW_PREVIEW_PAGES: '1', NODE_ENV: 'production' });
    }
    consoleProc = await serve(
      'console',
      CONSOLE_PORT,
      consoleArgv,
      join(ROOT, 'apps/console'),
      {
        ...consoleEnv,
        // Next locks its build directory and refuses a second server on it, so each run (its own console port) gets
        // its own, clear of `make up`'s console and of another session's run.
        OPS_CONSOLE_DIST_DIR: CONSOLE_DIST_DIR,
        OPS_CONSOLE_TSCONFIG: CONSOLE_TSCONFIG,
      },
      `${consoleUrl}/`,
      180_000,
    );
    if (options.embed) {
      embedTsconfig = readFileSync(join(ROOT, 'apps/embed/tsconfig.json'), 'utf8');
      writeRunTsconfig('apps/embed', EMBED_TSCONFIG);
      const embedUrl = `http://localhost:${EMBED_PORT}`;
      embedProc = await serve(
        'embed',
        EMBED_PORT,
        ['pnpm', 'exec', 'next', 'dev', '-p', String(EMBED_PORT)],
        join(ROOT, 'apps/embed'),
        {
          ...env,
          OPS_EMBED_AGENTS_URL: `http://127.0.0.1:${AGENTS_PORT}`,
          OPS_EMBED_DIST_DIR: EMBED_DIST_DIR,
          OPS_EMBED_TSCONFIG: EMBED_TSCONFIG,
          // The console may frame the embed page (frame-ancestors), for its Preview.
          OPS_CONSOLE_URL: consoleUrl,
        },
        // The loader route is the embed host's rewrite to agents-service, so it answers once both are up.
        `${embedUrl}/embed/v1.js`,
        180_000,
      );
      stack.embedUrl = embedUrl;
    }
    return await body(consoleUrl, stack);
  } finally {
    for (const w of workers) if (w.exitCode === null) stop(w);
    if (embedProc) {
      stop(embedProc);
      for (let i = 0; i < 40 && (await portBusy(EMBED_PORT)); i++) await new Promise((r) => setTimeout(r, 250));
      await new Promise((r) => setTimeout(r, 500));
      if (embedTsconfig !== undefined) {
        const after = readFileSync(join(ROOT, 'apps/embed/tsconfig.json'), 'utf8');
        check('apps/embed/tsconfig.json is as the run found it', after === embedTsconfig, 'the embed server wrote into the committed tsconfig');
      }
      try {
        rmSync(join(ROOT, 'apps/embed', EMBED_DIST_DIR), { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
        rmSync(join(ROOT, 'apps/embed', EMBED_TSCONFIG), { force: true });
      } catch {
        // As for the console below: cleanup never fails a run.
      }
    }
    if (consoleProc) {
      // The Next server (a child of pnpm) writes its build directory until it exits, after pnpm does; removing the
      // directory sooner leaves it recreated. It holds the console port until then.
      stop(consoleProc);
      for (let i = 0; i < 40 && (await portBusy(CONSOLE_PORT)); i++) await new Promise((r) => setTimeout(r, 250));
      await new Promise((r) => setTimeout(r, 500));
    }
    // Next writes its build directory's type globs into the tsconfig it reads. The run hands it its own, so a change to
    // the committed file means that broke, and the shared tree would carry the diff into someone's commit.
    if (committedTsconfig !== undefined) {
      const after = readFileSync(join(ROOT, 'apps/console/tsconfig.json'), 'utf8');
      check('apps/console/tsconfig.json is as the run found it', after === committedTsconfig, 'the console server wrote into the committed tsconfig');
    }
    // Cleanup never fails a run: a straggling write can still race the delete, which then leaves the folder behind.
    try {
      rmSync(join(ROOT, 'apps/console', CONSOLE_DIST_DIR), { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
      rmSync(join(ROOT, 'apps/console', CONSOLE_TSCONFIG), { force: true });
    } catch {
      // left for the next run's cleanup or a manual remove
    }
    if (platformProc) stop(platformProc);
    if (idpProc) stop(idpProc);
    if (stack.mailDir) rmSync(stack.mailDir, { recursive: true, force: true });
    if (toolsProc) stop(toolsProc);
    if (runnerProc) stop(runnerProc);
    if (kbProc) stop(kbProc);
    if (documentsProc) stop(documentsProc);
    if (filesProc) stop(filesProc);
    rmSync(filesDir, { recursive: true, force: true });
    opa?.stop();
    if (bankProc) {
      bankProc.stdin?.end();
      stop(bankProc);
    }
    stop(agents);
    if (modelsProc) stop(modelsProc);
    if (fakeOpenAi) stop(fakeOpenAi);
  }
}
