// uc-267 admins see roles, a person's effective access and why an action is refused, ui layer:
// docs/usecases/console/access-roles-and-checks.md (c-150). Platform sign-in as Wanjiru Kamau, whom the dev seed makes
// an admin of the Platform team and Admin in every team (a workspace admin), so her access is more than her team
// role says.
import { join } from 'node:path';
import { mkdirSync } from 'node:fs';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const SHOTS = join(ROOT, '.codeloop/evidence/150/screens');

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
    mkdirSync(SHOTS, { recursive: true });
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('w.kamau@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const shoot = async (name) => {
        for (const width of [1280, 400]) {
          await page.setViewportSize({ width, height: 800 });
          await page.waitForTimeout(600);
          await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`) });
        }
        await page.setViewportSize({ width: 1280, height: 800 });
      };

      await step('1 Access › Roles lists every role with what it grants and who holds it; a built-in role opens read-only', async () => {
        await page.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByText('Roles', { exact: true }).first().click();
        await page.waitForURL(/\/access\/roles$/);
        const rows = page.locator('[data-testid^="role-row-"]');
        await rows.first().waitFor();
        const names = (await rows.allInnerTexts()).map((t) => t.split('\n')[0].trim());
        await shoot('access-roles');
        await page.getByTestId('role-row-viewer').click();
        await page.waitForURL(/\/access\/roles\/viewer$/);
        const kind = (await page.getByTestId('role-kind').innerText()).trim();
        const viewCell = await page.getByTestId('cell-agents-view').count();
        const editCell = await page.getByTestId('cell-agents-edit').count();
        const editors = await page.getByRole('button', { name: /^(Edit|Save|Delete)/ }).count();
        await shoot('access-role');
        check(
          '1 Access › Roles lists every role with what it grants and who holds it; a built-in role opens read-only',
          names.includes('Viewer') && names.includes('Admin') && kind.startsWith('Built in · read-only') && viewCell === 1 && editCell === 0 && editors === 0,
          { names, kind, viewCell, editCell, editors },
        );
      });

      await step('2 Members shows access beyond the team role and where it comes from, and keeps the role in view on a phone', async () => {
        await page.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const ravi = page.getByRole('row', { name: /Wanjiru Kamau/ });
        await ravi.waitFor();
        const text = (await ravi.innerText()).replace(/\s+/g, ' ');
        // On a phone the role stays in view: it rides under the pinned name instead of a column off to the side.
        await page.setViewportSize({ width: 400, height: 800 });
        await page.waitForTimeout(500);
        const inline = ravi.locator('[data-testid^="member-role-inline-"]');
        // Scrolled to the table's far end, as a person reaching Status would: the pinned name, and the role in it, stay.
        await page.locator('table').first().locator('xpath=..').evaluate((el) => el.scrollTo(el.scrollWidth, 0));
        await page.waitForTimeout(300);
        const box = await inline.boundingBox();
        const phone = (await inline.innerText()).replace(/\s+/g, ' ');
        await page.setViewportSize({ width: 1280, height: 800 });
        check(
          '2 Members shows access beyond the team role and where it comes from, and keeps the role in view on a phone',
          /Admin/.test(text) && /Admin · every team/.test(text) && !!box && box.x >= 0 && box.x + box.width <= 400 && /Admin · every team/.test(phone),
          { text, phone, box },
        );
      });

      await step('3 A person opens on their effective access: every team and the team, each action with the role that grants it', async () => {
        await page.getByRole('row', { name: /Wanjiru Kamau/ }).locator('td').nth(3).click();
        await page.waitForURL(/\/access\/people\/[^/]+$/);
        const title = (await page.getByTestId('page-title').innerText()).trim();
        const every = page.getByTestId('grants-workspace');
        const wide = await every.waitFor({ timeout: 30_000 }).then(async () => (await every.innerText()).replace(/\s+/g, ' '), () => '');
        const teamSection = (await page.locator('[data-testid^="grants-team_platform"]').first().innerText().catch(() => '')).replace(/\s+/g, ' ');
        await shoot('access-person');
        check(
          '3 A person opens on their effective access: every team and the team, each action with the role that grants it',
          title === 'Wanjiru Kamau' && /Access/.test(wide) && /Manage/.test(wide) && /from Admin/.test(wide) && /from Admin/.test(teamSection),
          { title, wide: wide.slice(0, 200), teamSection: teamSection.slice(0, 200) },
        );
      });

      await step('4 Check access answers by the services\' own check: allowed with the role, then refused by the separation-of-duties policy', async () => {
        // Wanjiru acts in Operations, where Maya Okafor is a Reviewer.
        await page.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const switcher = page.getByRole('button', { name: /^Team: (?!loading).*\. Switch team$/ }).first();
        await switcher.waitFor({ timeout: 30_000 });
        await switcher.click();
        const items = (await page.getByRole('menuitem').allInnerTexts()).map((t) => t.split('\n')[0].trim());
        await page.getByRole('menuitem').nth(items.indexOf('Operations')).click();
        const maya = page.getByRole('row', { name: /Maya Okafor/ });
        if (!(await maya.waitFor({ timeout: 30_000 }).then(() => true, () => false)))
          throw new Error(`no Maya row after switching; menu ${JSON.stringify(items)}; rows ${(await page.locator('tbody').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 200)}`);
        await maya.locator('td').nth(3).click();
        await page.waitForURL(/\/access\/people\/[^/]+$/);
        // Shots are taken while the dialog is open, with its answer on screen.
        const ask = async (shotName) => {
          await page.getByTestId('check-access').click();
          const dialog = page.getByRole('dialog');
          await dialog.getByTestId('check-requested').fill('m.okafor@northfieldbank.com');
          const sent = page.waitForResponse((r) => r.url().endsWith('/v1/access/check'), { timeout: 30_000 });
          await dialog.getByTestId('check-run').click();
          await sent;
          const result = dialog.getByTestId('check-result');
          if (!(await result.waitFor({ timeout: 20_000 }).then(() => true, () => false))) throw new Error(`no result: ${(await dialog.innerText()).replace(/\s+/g, ' ').slice(0, 300)}`);
          const out = { allowed: await result.getAttribute('data-allowed'), said: (await result.innerText()).replace(/\s+/g, ' ') };
          if (shotName) {
            for (const width of [1280, 400]) {
              await page.setViewportSize({ width, height: 800 });
              await page.waitForTimeout(600);
              await page.screenshot({ path: join(SHOTS, `${shotName}-${width}.png`) });
            }
            await page.setViewportSize({ width: 1280, height: 800 });
          }
          await page.keyboard.press('Escape');
          return out;
        };
        const before = await ask('access-check');
        // The workspace stops a requester deciding their own request; the same check now refuses for that reason.
        const token = (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'w.kamau@northfieldbank.com', password: 'northfield-demo' }) })).json()).data.token;
        const off = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/policies/requesterMayDecide`, { method: 'PUT', headers: { Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_platform', 'Content-Type': 'application/json' }, body: JSON.stringify({ value: false }) });
        const after = await ask();
        check(
          '4 Check access answers by the services\' own check: allowed with the role, then refused by the separation-of-duties policy',
          before.allowed === 'true' && /Reviewer/.test(before.said) && off.status === 200 && after.allowed === 'false' && /someone else has to decide/.test(after.said),
          { before, policy: off.status, after },
        );
      });

      await step('5 A button the person may not use is shown locked, and its ⓘ says why and who can grant it', async () => {
        // James, a Builder of Operations, drafts an agent; Maya, a Reviewer there, opens it.
        const tokenOf = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
        const made = await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/agents`, { method: 'POST', headers: { Authorization: `Bearer ${await tokenOf('j.richardson@northfieldbank.com')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Locked publish desk', role: 'Answers balance questions' }) });
        const agent = (await made.json()).data;
        if (made.status >= 300) throw new Error(`setup: creating the agent answered ${made.status}`);
        const maya = await (await browser.newContext({ viewport: { width: 1280, height: 800 } })).newPage();
        maya.on('pageerror', (e) => errors.push(e.message));
        await maya.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await maya.getByLabel('Email').fill('m.okafor@northfieldbank.com');
        await maya.getByLabel('Password').fill('northfield-demo');
        await maya.getByRole('button', { name: /^Sign in/ }).first().click();
        await maya.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await maya.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const locked = maya.getByTestId('locked-agents-publish');
        if (!(await locked.waitFor({ timeout: 45_000 }).then(() => true, () => false))) {
          const header = (await maya.getByTestId('page-header').innerText().catch(() => '')).replace(/\s+/g, ' ');
          const detail = await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/agents/${agent.id}`, { headers: { Authorization: `Bearer ${await tokenOf('m.okafor@northfieldbank.com')}`, 'X-Team-Id': 'team_ops' } })).json();
          throw new Error(`no locked Publish; header: ${header.slice(0, 200)}; canPublish ${detail.data?.canPublish}; versions ${JSON.stringify((detail.data?.versions ?? []).map((v) => v.state))}`);
        }
        const disabled = await locked.isDisabled();
        await maya.getByTestId('locked-why').hover();
        const tip = maya.getByTestId('locked-why-text').first();
        await tip.waitFor({ timeout: 15_000 });
        // The reason is read from the server; wait for its roles to arrive.
        for (let i = 0; i < 20 && !/have it/.test(await tip.innerText()); i++) await maya.waitForTimeout(500);
        const said = (await tip.innerText()).replace(/\s+/g, ' ');
        // Each shot hovers again: resizing or the wait above can close the tooltip.
        for (const width of [1280, 400]) {
          await maya.setViewportSize({ width, height: 800 });
          await maya.mouse.move(0, 0);
          // Focus opens the tooltip as a keyboard user would, and holds it open where a hover may not survive a resize.
          await maya.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur());
          await maya.waitForTimeout(400);
          await maya.getByTestId('locked-why').focus();
          const open = await maya.locator('[data-testid="locked-why-text"][data-state$="open"]').first().waitFor({ state: 'visible', timeout: 8_000 }).then(() => true, () => false);
          if (!open) throw new Error(`tooltip closed at ${width}: trigger ${await maya.getByTestId('locked-why').getAttribute('data-state')}; tips ${JSON.stringify(await maya.locator('[data-testid="locked-why-text"]').evaluateAll((els) => els.map((e) => [e.getAttribute('data-state'), getComputedStyle(e).visibility, e.getBoundingClientRect().width])))}; focused ${await maya.evaluate(() => document.activeElement?.getAttribute('data-testid'))}`);
          await maya.waitForTimeout(400);
          await maya.screenshot({ path: join(SHOTS, `locked-why-${width}.png`) });
        }
        check(
          '5 A button the person may not use is shown locked, and its ⓘ says why and who can grant it',
          disabled && /Publish on Agents/.test(said) && /the Admin and Builder roles have it/.test(said) && /Ask /.test(said),
          { disabled, said },
        );
      });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
