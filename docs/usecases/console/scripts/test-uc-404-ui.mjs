// uc-404 The console says when its services are out of reach, when a session has ended and when a linked task is
// gone, ui layer: docs/usecases/console/services-unreachable.md. Platform sign-in as Priya. The outage is real: the
// run's own platform-service process is stopped, last, since nothing restarts it.
import { execFileSync } from 'node:child_process';

import { PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PRIYA = 'p.shah@northfieldbank.com';

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));
      const signIn = async () => {
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(PRIYA);
        await page.getByLabel('Password').fill('northfield-demo');
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      };
      await signIn();

      await step('1 a link to a task that does not exist says so and shows the queue', async () => {
        await page.goto(`${consoleUrl}/reviews?review=wfrun_000000000000:review:1`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const said = await page.getByText('That task wasn’t found or is closed').first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
        await page.waitForURL((u) => !u.searchParams.has('review'), { timeout: 15_000 }).catch(() => undefined);
        const url = new URL(page.url());
        check('1 a link to a task that does not exist says so and shows the queue', said && url.pathname === '/reviews' && !url.searchParams.has('review'), { said, url: page.url() });
      });

      await step('2 a session signed out elsewhere goes back to sign-in, keeping the page', async () => {
        // The browser's own session, ended on the server as another tab or an admin would.
        const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ops-platform-session') ?? '{}').token ?? null);
        const out = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-out`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
        await page.goto(`${consoleUrl}/cases`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.waitForURL((u) => u.pathname.startsWith('/login'), { timeout: 60_000 }).catch(() => undefined);
        const url = new URL(page.url());
        check('2 a session signed out elsewhere goes back to sign-in, keeping the page', out.status === 204 && url.pathname === '/login' && url.searchParams.get('next') === '/cases', { signOut: out.status, url: page.url() });
      });

      await step('3 with the services down, one screen says so with Try again', async () => {
        await signIn();
        // The run's platform-service: the process listening on its port.
        const pids = execFileSync('lsof', ['-ti', `tcp:${PLATFORM_PORT}`, '-sTCP:LISTEN']).toString().trim().split('\n').filter(Boolean);
        for (const pid of pids) process.kill(Number(pid), 'SIGTERM');
        for (let i = 0; i < 20; i++) {
          if (!(await fetch(`http://127.0.0.1:${PLATFORM_PORT}/health`).then(() => true, () => false))) break;
          await new Promise((r) => setTimeout(r, 500));
        }
        await page.reload({ waitUntil: 'domcontentloaded', timeout: 120_000 });
        const screen = page.getByTestId('services-unavailable');
        const shown = await screen.waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const said = shown ? (await screen.innerText()).replace(/\s+/g, ' ') : (await page.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 300);
        const retry = await page.getByTestId('services-retry').count();
        const others = await page.getByText(/Teams unavailable|Couldn.t load|Something went wrong/).count();
        check('3 with the services down, one screen says so with Try again', shown && /can.t reach its services/.test(said) && retry === 1 && others === 0, { pids: pids.length, said, retry, others });
      });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
