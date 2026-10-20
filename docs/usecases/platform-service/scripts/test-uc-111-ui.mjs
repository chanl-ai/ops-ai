// uc-111 a person stays signed in across make up, ui layer: docs/usecases/platform-service/signed-in-across-make-up.md.
// Drives the real `make up` on the isolated stack (ISOLATED=1, ports +1000; never the shared one) with platform
// sign-in. The database is left one migration behind the code, as pulling a commit with a newer migration leaves it;
// `make up` must migrate it in place, so the session and the data written before are still there. Each step alone.
import { execSync } from 'node:child_process';
import { ROOT, check, chromium, finish } from '@ops-ai/usecase-runner/harness';

const CONSOLE = 'http://localhost:4016';
const PLATFORM = 'http://127.0.0.1:9710';
const AGENTS = 'http://127.0.0.1:9700';
const DB = 'postgresql+asyncpg://ops:ops@localhost:6477/ops_runtime';
const KEY = 'ops-platform-session';
const TAG = Math.random().toString(36).slice(2, 7);
const AGENT = `Restart check ${TAG}`;
// The runner is itself started by make, which exports the shared stack's OPS_* ports and database URL; a nested make
// would take those over ISOLATED=1's own (env.mk assigns with ?=) and act on the shared stack. They are removed here.
const isolatedEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('OPS_') && !k.startsWith('MAKE') && k !== 'MFLAGS'));
const make = (args) => execSync(`make -C ${ROOT} ${args} ISOLATED=1 AUTH=platform`, { encoding: 'utf8', env: isolatedEnv, stdio: ['ignore', 'pipe', 'pipe'], timeout: 900_000 });
const stored = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) ?? 'null'), KEY);

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e.stdout ?? e).slice(-600));
    return undefined;
  }
}

async function open(page, path) {
  // The console may still be starting after make up returns.
  for (let i = 0; i < 60; i++) {
    try {
      await page.goto(`${CONSOLE}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      return;
    } catch {
      await page.waitForTimeout(2000);
    }
  }
}

make('up');
const browser = await chromium.launch();
const errors = [];
try {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  let before;

  // 1. James signs in and creates an agent: a session and a record the restart must keep.
  await step('1 signed in, with an agent saved', async () => {
    await open(page, '/login');
    await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
    await page.getByLabel('Password').fill('northfield-demo');
    await page.getByRole('button', { name: /^Sign in/ }).first().click();
    await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
    before = await stored(page);
    const r = await fetch(`${AGENTS}/v1/agents`, { method: 'POST', headers: { Authorization: `Bearer ${before.token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ name: AGENT, role: 'Checks restarts' }) });
    check('1 signed in, with an agent saved', !!before?.token && r.status < 300, { status: r.status });
  });

  // 2. The database falls one migration behind the code (kb's last), as after pulling a newer migration.
  await step('2 the database is one migration behind the code', async () => {
    execSync(`cd ${ROOT}/services/kb-service && OPS_DATABASE_URL=${DB} uv run --quiet alembic downgrade -1`, { env: isolatedEnv, stdio: 'pipe' });
    const out = execSync(`uv run --quiet --project ${ROOT} python ${ROOT}/scripts/schema_sync.py ${DB}`, { env: isolatedEnv, encoding: 'utf8' });
    check('2 the database is one migration behind the code', out.includes('kb database at') && out.includes('migrates it forward'), out.trim());
  });

  // 3. make up migrates in place: no wipe, the chain at head.
  await step('3 make up migrates in place', async () => {
    const out = make('up');
    const after = execSync(`uv run --quiet --project ${ROOT} python ${ROOT}/scripts/schema_sync.py ${DB}`, { env: isolatedEnv, encoding: 'utf8' });
    check('3 make up migrates in place', !/dropped and recreated/.test(out) && after.trim() === '', { tail: out.split('\n').slice(-4), after });
  });

  // 4. The same browser is still signed in, with the same session, and the agent is still there.
  await step('4 still signed in, and the data is there', async () => {
    await open(page, '/agents');
    await page.getByTestId('page-title').first().waitFor({ timeout: 120_000 });
    await page.waitForTimeout(3000);
    const now = await stored(page);
    const session = await fetch(`${PLATFORM}/v1/auth/session`, { headers: { Authorization: `Bearer ${now?.token}` } });
    const listed = await page.getByText(AGENT).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check(
      '4 still signed in, and the data is there',
      !page.url().includes('/login') && session.status === 200 && now?.refreshToken?.split('.')[0] === before?.refreshToken?.split('.')[0] && listed,
      { url: page.url(), session: session.status, listed },
    );
  });

  check('no page errors', errors.length === 0, errors);
} finally {
  await browser.close();
}
finish();
