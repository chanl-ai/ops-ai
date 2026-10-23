// uc-516 An account admin sees every background process and what it did, ui layer:
// docs/usecases/agents-service/an-account-admin-sees-every-background-process.md (c-516). The run's own demo stack;
// platform sign-in as Wanjiru (an Admin in every team), James (a builder of Operations) and Nadia (Security).
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const WANJIRU = 'w.kamau@harborpine.example';
const JAMES = 'j.richardson@harborpine.example';
const NADIA = 'n.petrov@harborpine.example';
const KEYS = ['workflow_worker', 'sweeper', 'timer_poller', 'memory_cleanup', 'mail_listener', 'event_workflows', 'files_relay', 'documents_relay', 'tools_relay', 'document_reading'];
const SHOTS = evidenceDir('516', 'screens');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const workerState = async () => (await (await fetch(`${agents}/health/background`)).json()).processes.find((p) => p.key === 'workflow_worker').state;

let current;
async function step(name, body) {
  try {
    await body();
  } catch (e) {
    if (current) await current.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => undefined);
    check(name, false, String(e).slice(0, 400));
  }
}

async function shots(page, name) {
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${name}-1280.png`), fullPage: true });
  await page.setViewportSize({ width: 400, height: 800 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, `${name}-400.png`), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

async function signIn(browser, consoleUrl, email) {
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  page.setDefaultTimeout(60_000);
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl, stack) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
    const N = { Authorization: `Bearer ${await tokenFor(NADIA)}`, 'X-Team-Id': 'team_security' };
    const browser = await chromium.launch();
    const errors = [];
    try {
      const admin = await signIn(browser, consoleUrl, WANJIRU);
      current = admin;
      admin.on('pageerror', (e) => errors.push(e.message));

      await step('1 an account admin sees every listed process, the sweeper running', async () => {
        await admin.goto(`${consoleUrl}/logs/background`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await admin.getByTestId('state-sweeper').waitFor({ timeout: 120_000 });
        const rows = await Promise.all(KEYS.map((k) => admin.getByTestId(`state-${k}`).count()));
        const sweeper = await admin.getByTestId('state-sweeper').innerText();
        await shots(admin, 'background');
        check('1 an account admin sees every listed process, the sweeper running', rows.every((n) => n === 1) && sweeper === 'Running', { rows: Object.fromEntries(KEYS.map((k, i) => [k, rows[i]])), sweeper });
      });

      await step('2 a builder is told the page is for account admins, and the API answers 404', async () => {
        const james = await signIn(browser, consoleUrl, JAMES);
        current = james;
        await james.goto(`${consoleUrl}/logs/background`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await james.getByTestId('background-admin-only').waitFor({ timeout: 60_000 });
        const api = await fetch(`${agents}/v1/background`, { headers: J });
        await shots(james, 'background-builder');
        check('2 a builder is told the page is for account admins, and the API answers 404', api.status === 404, { status: api.status });
        await james.context().close();
        current = admin;
      });

      await step('3 a stopped worker reads late after two gaps and stopped after five', async () => {
        const worker = await stack.startWorker();
        let running = false;
        for (let i = 0; i < 60 && !running; i++) {
          running = (await workerState()) === 'running';
          if (!running) await sleep(1000);
        }
        await worker.stop();
        const stoppedAt = Date.now();
        let late = false;
        while (!late && Date.now() - stoppedAt < 45_000) {
          late = (await workerState()) === 'late';
          if (!late) await sleep(2000);
        }
        const lateAfter = Math.round((Date.now() - stoppedAt) / 1000);
        let stopped = false;
        while (!stopped && Date.now() - stoppedAt < 90_000) {
          stopped = (await workerState()) === 'stopped';
          if (!stopped) await sleep(2000);
        }
        const stoppedAfter = Math.round((Date.now() - stoppedAt) / 1000);
        check('3 a stopped worker reads late after two gaps and stopped after five', running && late && stopped && lateAfter >= 10 && stoppedAfter >= 40, { running, late, lateAfter, stopped, stoppedAfter });
      });

      await step('4 a deleted file is purged by the event workflow and the job shows on the page and in Operations Activity only', async () => {
        const body = Buffer.from(`uc-516 ${Date.now()}\n`);
        const ticket = await data(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'uc516.txt', size: body.length, mime: 'text/plain', purpose: 'case_attachment' }) }));
        await fetch(new URL(ticket.uploadUrl, files).toString(), { method: 'PUT', headers: { ...J, ...ticket.headers }, body });
        const file = (await data(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: J }))).file;
        await data(await fetch(`${files}/v1/files/bulk-delete`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: [file.id] }) }));
        const jobOf = async (who) => (await data(await fetch(`${agents}/v1/activity?page=1&pageSize=25&kind=background`, { headers: who }))).data;
        let mine = [];
        for (let i = 0; i < 60 && mine.length === 0; i++) {
          mine = (await jobOf(J)).filter((r) => r.source.id === 'event_workflows');
          if (mine.length === 0) await sleep(1000);
        }
        const theirs = (await jobOf(N)).filter((r) => r.source.id === 'event_workflows' && r.teamId === 'team_ops');
        await admin.goto(`${consoleUrl}/logs/background`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await admin.getByText(mine[0]?.title ?? 'never').first().waitFor({ timeout: 60_000 });
        const team = await admin.locator('tr', { hasText: mine[0].title }).first().innerText();
        await shots(admin, 'background-job');
        check('4 a deleted file is purged by the event workflow and the job shows on the page and in Operations Activity only', mine.length > 0 && theirs.length === 0 && team.includes('Operations'), { mine: mine.map((r) => [r.title, r.teamId]), theirs: theirs.length, row: team.replace(/\s+/g, ' ') });
      });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
