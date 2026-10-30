// One test per way the runner could report a use case wrongly.
import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { test as runUseCases } from './cli.ts';
import { coverage } from './coverage.ts';
import { portBusy, serve, stackEnv } from './harness.ts';
import { DB_VAR, isolate, pgUrl, PORT_VARS } from './isolation.ts';
import { parseRegistry, RegistryError } from './registry.ts';
import { EXIT, exitFor, parseChecks, verdict } from './report.ts';
import { resolveScript } from './resolve.ts';
import { childEnv } from './run.ts';
import { scaffold } from './scaffold.ts';

const TABLE = `# Use cases

| Id | Service | Title | Layers | Status |
|---|---|---|---|---|
| uc-001 | agents-service | Chat turn with citation | api | passing |
| uc-002 | agents-service | Approval with step-up | api, ui | passing |
`;

function repo(): string {
  const root = mkdtempSync(join(tmpdir(), 'ucr-'));
  mkdirSync(join(root, 'docs/usecases/agents-service/scripts'), { recursive: true });
  mkdirSync(join(root, 'services/agents-service'), { recursive: true });
  mkdirSync(join(root, 'apps/console'), { recursive: true });
  writeFileSync(join(root, 'docs/usecases/README.md'), TABLE);
  writeFileSync(join(root, 'docs/README.md'), '| `usecases/README.md` | Registry |\n');
  return root;
}

test('registry rows parse with their layers', () => {
  const r = parseRegistry(TABLE);
  assert.deepEqual(r.map((u) => [u.id, u.layers]), [['uc-001', ['api']], ['uc-002', ['api', 'ui']]]);
});

test('a row with an unknown layer is refused, not silently dropped', () => {
  assert.throws(() => parseRegistry(TABLE.replace('api, ui', 'api, e2e')), RegistryError);
});

test('a duplicated id is refused', () => {
  assert.throws(() => parseRegistry(TABLE.replace('uc-002', 'uc-001')), /listed twice/);
});

test('a script that printed no check fails even with exit 0', () => {
  assert.deepEqual(verdict(0, parseChecks('started\nstopped\n')), { pass: false, reason: 'script printed no PASS line, so nothing was checked' });
});

test('a FAIL line fails the use case even when the script exits 0', () => {
  assert.equal(verdict(0, parseChecks('PASS a\nFAIL b: wrong\n')).pass, false);
});

test('a non-zero exit fails the use case even when every printed check passed', () => {
  assert.equal(verdict(1, parseChecks('PASS a\n')).pass, false);
});

test('all checks passing with exit 0 is a pass', () => {
  assert.equal(verdict(0, parseChecks('PASS a\nPASS b\n')).pass, true);
});

test('a layer whose provider does not exist is unavailable and says what to run', () => {
  const root = repo();
  const uc = parseRegistry(TABLE)[0]!;
  const r = resolveScript(root, uc, 'sdk');
  assert.equal(r.kind, 'unavailable');
  assert.match(r.kind === 'unavailable' ? r.reason : '', /run LAYER=api/);
});

test('a required layer with no script is missing, and a written one resolves', () => {
  const root = repo();
  const uc = parseRegistry(TABLE)[0]!;
  assert.equal(resolveScript(root, uc, 'api').kind, 'missing');
  writeFileSync(join(root, 'docs/usecases/agents-service/scripts/test-uc-001-api.py'), '');
  assert.deepEqual(resolveScript(root, uc, 'api'), {
    kind: 'script',
    path: 'docs/usecases/agents-service/scripts/test-uc-001-api.py',
    runtime: 'python',
  });
});

test('only-unavailable outcomes exit 3, so "nothing ran" is never reported as a pass', () => {
  assert.equal(exitFor([{ id: 'uc-001', layer: 'sdk', status: 'UNAVAILABLE', detail: '' }]), EXIT.unavailable);
  assert.equal(exitFor([{ id: 'uc-001', layer: 'api', status: 'PASS', detail: '' }, { id: 'uc-002', layer: 'api', status: 'FAIL', detail: '' }]), EXIT.failed);
});

test('model keys are removed unless APPROVED_REAL_CALLS is a positive count', () => {
  const keys = { OPENAI_API_KEY: 'k', ANTHROPIC_API_KEY: 'k' };
  for (const approved of [undefined, '', '0', 'yes']) {
    const { env, realCalls } = childEnv({ ...keys, APPROVED_REAL_CALLS: approved }, '/r');
    assert.equal(env.OPENAI_API_KEY, undefined, `kept with APPROVED_REAL_CALLS=${approved}`);
    assert.equal(realCalls, 0);
  }
  const { env, realCalls } = childEnv({ ...keys, APPROVED_REAL_CALLS: '5' }, '/r');
  assert.equal(env.OPENAI_API_KEY, 'k');
  assert.equal(realCalls, 5);
});

test('coverage marks a missing required script apart from a layer that does not exist yet', () => {
  const root = repo();
  const [row] = coverage(root, parseRegistry(TABLE), 'agents-service').filter((r) => r.id === 'uc-002');
  assert.deepEqual(row!.cells, { api: 'missing', sdk: 'not available yet', cli: 'not available yet', ui: 'missing' });
});

test('new takes the next id, registers it, and its stub script fails until written', () => {
  const root = repo();
  const made = scaffold(root, parseRegistry(TABLE), 'agents-service', 'Thread list by graph');
  assert.equal(made.id, 'uc-003');
  assert.match(readFileSync(join(root, 'docs/usecases/README.md'), 'utf8'), /\| uc-003 \| agents-service \| Thread list by graph \| api \| draft \|/);
  assert.match(readFileSync(join(root, 'docs/README.md'), 'utf8'), /usecases\/agents-service\/thread-list-by-graph\.md/);
  const stub = readFileSync(join(root, 'docs/usecases/agents-service/scripts/test-uc-003-api.py'), 'utf8');
  assert.match(stub, /check\("1 script written", False/);
});

test('the ui harness starts the services of the tree the runner was invoked from', () => {
  const other = repo();
  assert.equal(childEnv({}, other).env.OPS_USECASE_ROOT, other);
  // Imported the way a ui script imports it, with the runner's environment: ROOT must be that tree, not this package's.
  const harness = new URL('./harness.ts', import.meta.url).href;
  const printed = execFileSync(process.execPath, ['--input-type=module', '-e', `const m = await import(${JSON.stringify(harness)}); console.log(m.ROOT)`], {
    env: { ...process.env, OPS_USECASE_ROOT: other },
    encoding: 'utf8',
  });
  assert.equal(printed.trim(), other);
});

test('a service that never gets healthy is stopped when the harness gives up, so its port is free for the next run', async () => {
  const port = await new Promise<number>((done) => {
    const s = createServer().listen(0, '127.0.0.1', () => {
      const p = (s.address() as { port: number }).port;
      s.close(() => done(p));
    });
  });
  const stuck = `require('node:http').createServer((q, r) => { r.statusCode = 503; r.end(); }).listen(${port}, '127.0.0.1')`;
  await assert.rejects(serve('stuck', port, [process.execPath, '-e', stuck], tmpdir(), process.env, `http://127.0.0.1:${port}/`, 2_000), /not ready/);
  await new Promise((r) => setTimeout(r, 500));
  assert.equal(await portBusy(port), false);
});

test('a run stopped by SIGTERM leaves no process of its stack, even a wrapper that ignores SIGTERM', async () => {
  const port = await new Promise<number>((done) => {
    const s = createServer().listen(0, '127.0.0.1', () => {
      const p = (s.address() as { port: number }).port;
      s.close(() => done(p));
    });
  });
  const marker = `UCR_TEARDOWN_${process.pid}_${port}`;
  // A service shaped like pnpm: it ignores SIGTERM and its server child keeps running under it. The marker is in each
  // process's arguments, which ps shows; macOS does not show another process's environment.
  const service = [
    `// ${marker}`,
    "process.on('SIGTERM', () => {});",
    `require('node:child_process').spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000) // ${marker}'], { stdio: 'ignore' });`,
    `require('node:http').createServer((q, r) => r.end('ok')).listen(${port}, '127.0.0.1');`,
  ].join('\n');
  const run = [
    `import { serve } from ${JSON.stringify(new URL('./harness.ts', import.meta.url).href)};`,
    `await serve('teardown', ${port}, [process.execPath, '-e', ${JSON.stringify(service)}], process.cwd(), process.env, 'http://127.0.0.1:${port}/', 10_000);`,
    "console.log('ready');",
    'setInterval(() => {}, 1000);',
  ].join('\n');
  const left = () => execFileSync('ps', ['-axww', '-o', 'pid=,command='], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).split('\n').filter((l) => l.includes(marker));
  const child = spawn(process.execPath, ['--input-type=module', '-e', run], { cwd: tmpdir(), stdio: ['ignore', 'pipe', 'inherit'] });
  try {
    await new Promise<void>((done, fail) => {
      child.stdout!.on('data', (d: Buffer) => d.toString().includes('ready') && done());
      child.once('exit', (code) => fail(new Error(`the run exited with ${code} before its service was ready`)));
    });
    assert.ok(left().length >= 3, 'the run, its service and the service child are running');
    child.kill('SIGTERM');
    await new Promise((r) => child.once('exit', r));
    let still = left();
    for (let i = 0; i < 20 && still.length; i++) await new Promise((r) => setTimeout(r, 250)), (still = left());
    assert.deepEqual(still, []);
  } finally {
    child.kill('SIGKILL');
    for (const line of left()) process.kill(Number(line.trim().split(' ')[0]), 'SIGKILL');
  }
});

test('a Python use case stopped by SIGTERM leaves no process of its services, even one that ignores SIGTERM', async () => {
  const port = await new Promise<number>((done) => {
    const s = createServer().listen(0, '127.0.0.1', () => {
      const p = (s.address() as { port: number }).port;
      s.close(() => done(p));
    });
  });
  const marker = `UCR_PY_TEARDOWN_${process.pid}_${port}`;
  const dir = mkdtempSync(join(tmpdir(), 'ucr-py-'));
  // The service ignores SIGTERM and starts a child of its own, as a wrapper does; the marker is in every argv.
  writeFileSync(
    join(dir, 'service.py'),
    [
      `# ${marker}`,
      'import http.server, signal, subprocess, sys',
      'signal.signal(signal.SIGTERM, signal.SIG_IGN)',
      `subprocess.Popen([sys.executable, "-c", "import time  # ${marker}\\nwhile True: time.sleep(1)"])`,
      'class H(http.server.BaseHTTPRequestHandler):',
      '    def do_GET(self):',
      '        self.send_response(200)',
      '        self.end_headers()',
      '    def log_message(self, *a):',
      '        pass',
      `http.server.HTTPServer(("127.0.0.1", ${port}), H).serve_forever()`,
    ].join('\n'),
  );
  writeFileSync(
    join(dir, 'run.py'),
    [
      'import os, sys, time',
      'from usecase_harness import _serve',
      `with _serve("teardown", [sys.executable, ${JSON.stringify(join(dir, 'service.py'))}], ${port}, dict(os.environ)):`,
      '    print("ready", flush=True)',
      '    while True:',
      '        time.sleep(1)',
    ].join('\n'),
  );
  const root = new URL('../../../', import.meta.url).pathname;
  const left = () => execFileSync('ps', ['-axww', '-o', 'pid=,command='], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).split('\n').filter((l) => l.includes(marker) || l.includes(join(dir, 'service.py')));
  const child = spawn('uv', ['run', '--quiet', '--directory', join(root, 'services/agents-service'), 'python', join(dir, 'run.py')], {
    env: { ...process.env, PYTHONPATH: join(root, 'docs/usecases/lib') },
    stdio: ['ignore', 'pipe', 'inherit'],
  });
  try {
    await new Promise<void>((done, fail) => {
      child.stdout!.on('data', (d: Buffer) => d.toString().includes('ready') && done());
      child.once('exit', (code) => fail(new Error(`the script exited with ${code} before its service was ready`)));
    });
    assert.ok(left().length >= 2, 'the service and its child are running');
    child.kill('SIGTERM');
    await new Promise((r) => child.once('exit', r));
    let still = left();
    for (let i = 0; i < 60 && still.length; i++) await new Promise((r) => setTimeout(r, 250)), (still = left());
    assert.deepEqual(still, []);
  } finally {
    child.kill('SIGKILL');
    for (const line of left()) process.kill(Number(line.trim().split(' ')[0]), 'SIGKILL');
  }
});

test('a Python service whose group holds only an exited process stops cleanly, as macOS refuses signals to it', () => {
  // macOS answers EPERM, not ESRCH, to a signal for a group whose only members have exited and wait to be reaped.
  const root = new URL('../../../', import.meta.url).pathname;
  const script = [
    'import subprocess, sys, time',
    'from usecase_harness import _stop',
    'proc = subprocess.Popen(["true"], start_new_session=True)',
    'time.sleep(0.5)',
    '_stop(proc, grace=2)',
    'print("stopped", proc.returncode)',
  ].join('\n');
  const out = execFileSync('uv', ['run', '--quiet', '--directory', join(root, 'services/agents-service'), 'python', '-c', script], {
    env: { ...process.env, PYTHONPATH: join(root, 'docs/usecases/lib') },
    encoding: 'utf8',
  });
  assert.match(out, /stopped 0/);
});

test('a use case sets the agents service env, and model keys never reach it', () => {
  const env = stackEnv({ OPENAI_API_KEY: 'k', PATH: '/bin' }, { OPS_REGISTRY_AUTO_APPROVE: 'false', ANTHROPIC_API_KEY: 'x' });
  assert.equal(env.OPS_REGISTRY_AUTO_APPROVE, 'false');
  assert.equal(env.PATH, '/bin');
  assert.equal(env.OPENAI_API_KEY, undefined);
  assert.equal(env.ANTHROPIC_API_KEY, undefined);
});

test("the shared stack's models-service route does not reach a use case unless the use case passes it", () => {
  const shared = { OPS_MODELS_URL: 'http://127.0.0.1:8730', OPS_MODELS_KEY: 'dev', OPS_MODELS_FAKE_OPENAI_URL: 'http://127.0.0.1:8746' };
  const env = stackEnv(shared);
  assert.deepEqual([env.OPS_MODELS_URL, env.OPS_MODELS_KEY, env.OPS_MODELS_FAKE_OPENAI_URL], [undefined, undefined, undefined]);
  assert.equal(stackEnv(shared, { OPS_MODELS_URL: 'http://127.0.0.1:9000' }).OPS_MODELS_URL, 'http://127.0.0.1:9000');
});

test("the shared stack's platform-service does not reach a use case that runs without one", () => {
  // A run without platform-service still has the shared stack's exported OPS_PLATFORM_URL; with it, each service
  // builds a policy reader that gets 404s and fails closed (uc-019's dev auto-approve opened a review).
  assert.equal(stackEnv({ OPS_PLATFORM_URL: 'http://127.0.0.1:8710' }).OPS_PLATFORM_URL, undefined);
  assert.equal(stackEnv({}, { OPS_PLATFORM_URL: 'http://127.0.0.1:9710' }).OPS_PLATFORM_URL, 'http://127.0.0.1:9710');
});

// Stands in for a harness script: holds the agents port and claims the database (a directory per name) the way the
// harness defaults them, and fails when another run already holds either.
const CLAIMS = `
import { mkdirSync, rmSync } from 'node:fs';
import { createServer } from 'node:net';
const port = Number(process.env.OPS_USECASE_AGENTS_PORT ?? 8790);
const db = process.env.OPS_USECASE_DB ?? 'ops_usecase';
const claim = new URL('../../../db-' + db, import.meta.url);
try { mkdirSync(claim); } catch { console.log('FAIL database ' + db + ' is in use by another run'); process.exit(1); }
const s = createServer().once('error', () => { console.log('FAIL port ' + port + ' is in use'); process.exit(1); });
s.listen(port, '127.0.0.1', () => setTimeout(() => { s.close(); rmSync(claim, { recursive: true }); console.log('PASS ran alone'); }, 1500));
`;

test('two runs at once each get their own database and ports, and each drops only its own database', async () => {
  const root = repo();
  writeFileSync(join(root, 'docs/usecases/agents-service/scripts/test-uc-001-api.mjs'), CLAIMS);
  const parent = { ...process.env };
  for (const k of [...PORT_VARS, DB_VAR]) delete parent[k];
  const dropped: string[] = [];
  const drop = async (_root: string, _env: NodeJS.ProcessEnv, name: string) => (dropped.push(name), true);
  const registry = parseRegistry(TABLE);
  const codes = await Promise.all([1, 2].map(() => runUseCases(root, registry, 'uc-001', 'api', { parent, drop })));
  assert.deepEqual(codes, [EXIT.ok, EXIT.ok]);
  assert.equal(new Set(dropped).size, 2);
  for (const name of dropped) assert.match(name, /^ops_usecase_r\d+_[0-9a-f]{6}$/);
});

// Stands in for a harness script that reads what an earlier script left: it notes its database, and fails when that
// database is one a script before it used.
const USED = `
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
const log = new URL('../../../databases-used', import.meta.url);
const db = process.env.OPS_USECASE_DB;
const seen = existsSync(log) ? readFileSync(log, 'utf8').split('\\n') : [];
appendFileSync(log, db + '\\n');
console.log(seen.includes(db) ? 'FAIL ' + db + ' holds an earlier use case\\'s rows' : 'PASS ' + db + ' is new');
`;

test('each use case in a run gets its own database, dropped before the next one starts', async () => {
  const root = repo();
  for (const id of ['uc-001', 'uc-002']) writeFileSync(join(root, `docs/usecases/agents-service/scripts/test-${id}-api.mjs`), USED);
  const parent = { ...process.env };
  for (const k of [...PORT_VARS, DB_VAR]) delete parent[k];
  const used = () => readFileSync(join(root, 'docs/databases-used'), 'utf8').trim().split('\n');
  const dropped: { name: string; scriptsRun: number }[] = [];
  const drop = async (_root: string, _env: NodeJS.ProcessEnv, name: string) => (dropped.push({ name, scriptsRun: used().length }), true);
  assert.equal(await runUseCases(root, parseRegistry(TABLE), undefined, 'api', { parent, drop }), EXIT.ok);
  const names = used();
  assert.equal(new Set(names).size, 2, names.join());
  assert.deepEqual(dropped, [{ name: names[0], scriptsRun: 1 }, { name: names[1], scriptsRun: 2 }]);
});

test("a database URL follows make/env.mk: the devcontainer's postgres side container, else this machine's port", () => {
  assert.equal(pgUrl('ops_x', 'postgresql+asyncpg', { OPS_INFRA: 'external', OPS_PG_PORT: '5477' }), 'postgresql+asyncpg://ops:ops@postgres:5432/ops_x');
  assert.equal(pgUrl('postgres', 'postgresql', { OPS_PG_PORT: '6477' }), 'postgresql://ops:ops@localhost:6477/postgres');
  assert.equal(pgUrl('ops_x', 'postgresql+asyncpg', {}), 'postgresql+asyncpg://ops:ops@localhost:5477/ops_x');
});

test('explicit use-case ports and database win, are never dropped, and a chosen port is never a stack port', async () => {
  const given = await isolate({ OPS_USECASE_AGENTS_PORT: '8790', OPS_USECASE_DB: 'mine' });
  assert.equal(given.env.OPS_USECASE_AGENTS_PORT, '8790');
  assert.equal(given.env.OPS_USECASE_DB, 'mine');
  assert.equal(given.ownedDb, undefined);
  const stack = [3016, 3017, 8700, 8720, 8740, 8181, 5477];
  for (const k of PORT_VARS.slice(1)) assert.ok(!stack.includes(Number(given.env[k])) && given.env[k] !== '8790', k);
  // Every service a demo stack starts gets its own port, so two demo runs never share kb-service or the fake OpenAI.
  const ports = PORT_VARS.map((k) => given.env[k]);
  assert.ok(ports.every(Boolean) && new Set(ports).size === PORT_VARS.length, JSON.stringify(ports));
  assert.ok(PORT_VARS.includes('OPS_USECASE_KB_PORT') && PORT_VARS.includes('OPS_USECASE_FAKE_OPENAI_PORT') && PORT_VARS.includes('OPS_USECASE_FILES_PORT'));
});

test("a console build is keyed on What's new: a changed entry or roadmap item makes a new build (c-510)", async () => {
  const { buildKey } = await import('./console-build.ts');
  const root = mkdtempSync(join(tmpdir(), 'console-key-'));
  const app = join(root, 'apps', 'console');
  mkdirSync(join(app, 'src'), { recursive: true });
  mkdirSync(join(root, 'changelog'));
  writeFileSync(join(app, 'src', 'page.tsx'), 'x');
  writeFileSync(join(root, 'changelog', 'a.json'), '{"title":"A"}');
  writeFileSync(join(root, 'roadmap.json'), '[]');
  const before = buildKey(app, {});
  writeFileSync(join(root, 'changelog', 'a.json'), '{"title":"B"}');
  const entryChanged = buildKey(app, {});
  writeFileSync(join(root, 'roadmap.json'), '[{"title":"Next"}]');
  assert.notEqual(entryChanged, before);
  assert.notEqual(buildKey(app, {}), entryChanged);
});
