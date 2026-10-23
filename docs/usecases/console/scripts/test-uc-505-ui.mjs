// uc-505 Pages wait for the session and team, ui layer: docs/usecases/console/pages-wait-for-the-team.md (c-505). A private
// stack with platform sign-in. 1 the tab remembers Security from someone before,
// James (Operations only) signs in straight to an Operations case: no request fails and the case shows; 2 a case that
// does not exist says "Not found, or in another team" with a way to switch team; 3 a fresh sign-in loads three list
// pages with no failed request. Every API request is logged with its team and status in the card's evidence folder.
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const SHOTS = evidenceDir('505', 'uc');

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    mkdirSync(SHOTS, { recursive: true });
    const james = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const made = await fetch(`${agents}/v1/cases`, { method: 'POST', headers: james, body: JSON.stringify({ subject: 'Charged twice (uc-505)', priority: 'high' }) });
    if (made.status >= 300) throw new Error(`setup: opening a case answered ${made.status} ${(await made.text()).slice(0, 200)}`);
    const caseId = (await made.json()).data.id;
    // The switch lists James's other teams, so it shows only when he holds more than one.
    const teams = (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/teams`, { headers: james })).json()).data.length;
    const browser = await chromium.launch();
    const errors = [];
    const logAll = [];
    /** A new tab, optionally remembering a team, signed in as James straight to `next`; every API request logged. */
    const signedIn = async (next, remembered) => {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const page = await ctx.newPage();
      const log = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('response', (r) => {
        const u = new URL(r.url());
        if (![String(AGENTS_PORT), String(PLATFORM_PORT)].includes(u.port)) return;
        log.push({ status: r.status(), path: `${r.request().method()} ${u.pathname}`, team: r.request().headers()['x-team-id'] ?? null });
      });
      await page.goto(`${consoleUrl}/login?next=${encodeURIComponent(next)}`, { waitUntil: 'domcontentloaded', timeout: 180_000 });
      if (remembered) await page.evaluate((t) => sessionStorage.setItem('ops-team', t), remembered);
      await page.getByLabel('Work email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByTestId('login-submit').click();
      await page.waitForURL((u) => u.pathname === next.split('?')[0], { timeout: 120_000 });
      return { page, ctx, log };
    };
    const failed = (log) => log.filter((l) => l.status >= 400 && !l.path.endsWith('/v1/auth/sign-in'));
    try {
      await step('1 a tab that remembers another team signs in straight to a case with no failed request', async () => {
        const { page, ctx, log } = await signedIn(`/cases/${caseId}`, 'team_security');
        await page.getByText('Charged twice (uc-505)').first().waitFor({ timeout: 60_000 });
        await page.waitForTimeout(3000);
        await page.screenshot({ path: join(SHOTS, 'case-after-sign-in-1280.png') });
        logAll.push({ step: 1, log });
        check('1 a tab that remembers another team signs in straight to a case with no failed request', failed(log).length === 0 && log.some((l) => l.path.endsWith(`/v1/cases/${caseId}`) && l.status === 200), { failed: failed(log), teams: [...new Set(log.map((l) => l.team))] });
        await ctx.close();
      });

      await step('2 a case that does not exist says not found, or in another team, with a team switch', async () => {
        const { page, ctx, log } = await signedIn('/cases/case_000000000000');
        const state = page.getByTestId('query-not-found');
        await state.waitFor({ timeout: 60_000 });
        const text = (await state.innerText()).replace(/\s+/g, ' ');
        await page.screenshot({ path: join(SHOTS, 'case-not-found-1280.png') });
        logAll.push({ step: 2, log });
        check('2 a case that does not exist says not found, or in another team, with a team switch', /not found, or in another team/i.test(text) && (await state.getByRole('button', { name: /switch team/i }).count()) === (teams > 1 ? 1 : 0), { text, teams });
        await ctx.close();
      });

      await step('3 a fresh sign-in loads three list pages with no failed request', async () => {
        const { page, ctx, log } = await signedIn('/cases');
        for (const path of ['/cases', '/workflows/runs', '/reviews']) {
          if (path !== '/cases') await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded' });
          await page.waitForTimeout(4000);
        }
        logAll.push({ step: 3, log });
        check('3 a fresh sign-in loads three list pages with no failed request', failed(log).length === 0 && log.length > 3, { failed: failed(log), requests: log.length });
        await ctx.close();
      });
      check('4 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      writeFileSync(join(SHOTS, 'requests.json'), JSON.stringify(logAll, null, 1));
      await browser.close();
    }
  },
  { platform: true },
);
finish();
