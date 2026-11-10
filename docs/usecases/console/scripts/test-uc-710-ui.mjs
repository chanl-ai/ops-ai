// uc-710 a new row shows right after it is added, ui layer: docs/usecases/console/new-row-shows-after-add.md. The
// Egress hosts list is paged by name on tools-service; with a full page of hosts that sort before it, or a search typed
// that it does not match, a new host would land out of view unless the shared data table keeps it there.
import { join } from 'node:path';
import { mkdirSync } from 'node:fs';

import { PLATFORM_PORT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const PASSWORD = 'northfield-demo';
const ADMIN = 's.adeyemi@harborpine.example';
const MEMBER = 'r.menon@harborpine.example';
const shots = evidenceDir('uc-710');
mkdirSync(shots, { recursive: true });
const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

const signIn = async (browser, consoleUrl, email) => {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};
const shoot = async (page, name) => {
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    await page.waitForTimeout(300);
    await page.screenshot({ path: join(shots, `${name}-${width}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
};

await withUiStack(
  async (consoleUrl) => {
    const token = await tokenFor(ADMIN);
    const auth = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_security' };
    const seeded = Array.from({ length: 12 }, (_, i) => `a${String(i + 1).padStart(2, '0')}.uc710.example.com`);
    for (const h of seeded) await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: auth, body: JSON.stringify({ value: h, note: 'Listed before' }) });

    const browser = await chromium.launch();
    try {
      const admin = await signIn(browser, consoleUrl, ADMIN);
      await admin.goto(`${consoleUrl}/settings/egress`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const hosts = admin.getByTestId('egress-hosts');
      await hosts.getByText(seeded[0], { exact: true }).waitFor({ timeout: 120_000 });
      const add = async (value) => {
        await admin.getByRole('button', { name: 'Add host' }).click();
        const d = admin.getByRole('dialog', { name: 'Add a host' });
        await d.getByLabel('Host').fill(value);
        await d.getByLabel('Note').fill('Statements API');
        const res = armed(admin.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${tools}/v1/egress/hosts`, { timeout: 60_000 }));
        await d.getByTestId('egress-add-submit').click();
        const status = (await res)?.status();
        const row = hosts.locator('tr[data-created]', { hasText: value });
        const shown = await row.waitFor({ timeout: 15_000 }).then(() => true, () => false);
        return { status, shown, marked: shown && (await row.innerText()).includes('New'), hosts: (await hosts.innerText()).slice(0, 500) };
      };

      const late = await add('zz-late.uc710.example.com');
      check('a new host that sorts onto a later page shows right after it is added, marked New', late.status === 201 && late.shown && late.marked, late);
      await shoot(admin, 'admin-new-row-on-a-later-page');

      await hosts.getByRole('button', { name: 'Host' }).click();
      await admin.getByRole('menuitem', { name: 'Asc' }).click();
      const resorted = await hosts.locator('tr[data-created]').waitFor({ state: 'detached', timeout: 15_000 }).then(() => true, () => false);
      check('the new row follows the list again once the person sorts it', resorted, (await hosts.innerText()).slice(0, 500));

      const search = hosts.getByPlaceholder('Search hosts or notes…');
      await search.fill('a0');
      await hosts.getByText('a10.uc710.example.com', { exact: true }).waitFor({ state: 'detached', timeout: 30_000 });
      const hidden = await add('zz-search.uc710.example.com');
      check('a new host shows right after it is added while a search it does not match is typed', hidden.status === 201 && hidden.shown && hidden.marked, hidden);
      await shoot(admin, 'admin-new-row-under-a-search');

      await search.fill('a1');
      const dropped = await hosts.getByText('zz-search.uc710.example.com', { exact: true }).waitFor({ state: 'detached', timeout: 15_000 }).then(() => true, () => false);
      check('the new row follows the search again once the person changes it', dropped, (await hosts.innerText()).slice(0, 500));

      await search.fill('');
      await hosts.getByText(seeded[0], { exact: true }).waitFor({ timeout: 30_000 });
      const again = await add(seeded[0]);
      const copies = await hosts.getByRole('row', { name: new RegExp(`^${seeded[0].replace(/\./g, '\\.')}`) }).count();
      check('a host added again shows once, marked New, where the page also lists it', again.status === 200 && again.marked && copies === 1, { ...again, copies });

      // The ranges list is small and paged in the browser; the same table keeps its new row in view.
      await admin.getByRole('button', { name: 'Add range' }).click();
      const rd = admin.getByRole('dialog', { name: 'Add a private range' });
      await rd.getByLabel('Range').fill('10.77.0.0/16');
      await rd.getByLabel('Note').fill('Branch network');
      const rangeRes = armed(admin.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${tools}/v1/egress/ranges`, { timeout: 60_000 }));
      await rd.getByTestId('egress-add-submit').click();
      const rangeStatus = (await rangeRes)?.status();
      const rangeRow = admin.getByTestId('egress-ranges').locator('tr[data-created]', { hasText: '10.77.0.0/16' });
      const rangeShown = await rangeRow.waitFor({ timeout: 15_000 }).then(() => true, () => false);
      check('a new private range shows right after it is added, marked New', rangeStatus === 201 && rangeShown && (await rangeRow.innerText()).includes('New'), { rangeStatus, rangeShown });
      check('no page errors for the admin', admin.errors.length === 0, admin.errors);

      const member = await signIn(browser, consoleUrl, MEMBER);
      await member.goto(`${consoleUrl}/settings/egress`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await member.getByTestId('egress-hosts').getByText(seeded[0], { exact: true }).waitFor({ timeout: 120_000 });
      check('a member reads the hosts and has no Add host', (await member.getByRole('button', { name: 'Add host' }).count()) === 0);
      await shoot(member, 'member-reads-the-list');
      check('no page errors for the member', member.errors.length === 0, member.errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
