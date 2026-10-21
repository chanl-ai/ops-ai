// uc-164 workspace admins create, rename, archive and restore teams, ui layer. Headless Chromium against a console
// signed in through platform-service (dev seed): Wanjiru (workspace admin, Admin in every team) manages teams on
// Access > Teams; James (builder) sees that workspace admins do and no control.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const SHOTS = join(ROOT, '.codeloop/evidence/198');

async function signIn(page, consoleUrl, email) {
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      mkdirSync(SHOTS, { recursive: true });
      const sam = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
      const errors = [];
      sam.on('pageerror', (e) => errors.push(e.message));
      await signIn(sam, consoleUrl, 'w.kamau@harborpine.example');
      await sam.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const link = sam.getByTestId('access-teams');
      const linked = await link.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('Access offers Teams to a workspace admin', linked);
      await link.click();
      await sam.waitForURL((u) => u.pathname === '/access/teams', { timeout: 60_000 });
      await sam.getByTestId('teams-create').waitFor({ timeout: 60_000 });

      await sam.getByTestId('teams-create').click();
      await sam.getByLabel('Name').fill('Lending');
      await sam.getByLabel('First admin').fill('r.menon@harborpine.example');
      await sam.getByLabel('First admin').press('Enter');
      const row = sam.getByRole('row', { name: /Lending/ });
      const created = await row.waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('Enter creates Lending, listed with its first admin counted by the API', created && (await row.innerText()).replace(/\s+/g, ' ').includes('1 1'), created ? await row.innerText() : 'no row');
      await sam.screenshot({ path: join(SHOTS, 'uc-164-teams.png') });

      await sam.getByTestId('teams-create').click();
      await sam.getByLabel('Name').fill('lending');
      await sam.getByLabel('First admin').fill('r.menon@harborpine.example');
      await sam.getByTestId('team-submit').click();
      const taken = await sam.getByText('Another team in this workspace has that name.').waitFor({ timeout: 15_000 }).then(() => true, () => false);
      check('a second lending in another case is refused under the name field', taken);
      await sam.keyboard.press('Escape');

      await row.getByRole('button').last().click();
      await sam.getByRole('menuitem', { name: 'Archive' }).click();
      await sam.getByRole('button', { name: 'Archive team' }).click();
      const archived = await sam.getByRole('row', { name: /Lending.*Archived/ }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('Wanjiru archives Lending after confirming', archived);
      const security = sam.getByRole('row', { name: /Security/ }).first();
      await security.getByRole('button').last().click();
      const offered = (await sam.getByRole('menuitem').allInnerTexts()).map((t) => t.trim());
      await sam.keyboard.press('Escape');
      check('the Security team offers Rename and no Archive', offered.includes('Rename') && !offered.includes('Archive'), offered);
      check('no page errors for Wanjiru', errors.length === 0, errors);

      // At phone width the list scrolls inside its wrapper, never the page.
      await sam.setViewportSize({ width: 400, height: 860 });
      const wide = await sam.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
      check('the Teams page fits 400 px with no page scroll', !wide);

      const james = await (await browser.newContext({ viewport: { width: 1280, height: 860 } })).newPage();
      await signIn(james, consoleUrl, 'j.richardson@harborpine.example');
      await james.goto(`${consoleUrl}/access/teams`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const refused = await james.getByTestId('teams-no-access').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('James sees that workspace admins manage teams, and no Create team', refused && (await james.getByTestId('teams-create').count()) === 0);
      await james.screenshot({ path: join(SHOTS, 'uc-164-no-access.png') });
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
