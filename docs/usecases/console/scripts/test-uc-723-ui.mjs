// uc-723 the console shows one area of pages at a time, chosen from the top bar, ui layer:
// docs/usecases/console/console-areas.md. Headless Chromium on the demo stack, signed in through platform-service as the
// seeded people (services/platform-service/seed/people.json) and the fixtures added for this card: Lena (chat only) and
// Tomas (a builder in Operations, a chat user in Platform). Nothing names a role: what a person is offered is what
// their cells open. Screenshots go to evidenceDir('723', 'uc').
//
// UC723_STEPS=1,4 runs only those steps.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const PRIYA = 'p.shah@harborpine.example';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const RAVI = 'r.menon@harborpine.example';
const LENA = 'l.brandt@harborpine.example';
const TOMAS = 't.reyes@harborpine.example';
const WANJIRU = 'w.kamau@harborpine.example';
const AREAS = ['Work', 'Build', 'Data', 'Govern'];
const SHOTS = evidenceDir('723', 'uc');
const ONLY = process.env.UC723_STEPS?.split(',').map((x) => x.trim());

async function step(name, body) {
  if (ONLY && !ONLY.includes(name.split(' ')[0])) return;
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 500));
  }
}

await withUiStack(
  async (consoleUrl) => {
    mkdirSync(SHOTS, { recursive: true });
    const browser = await chromium.launch();
    const errors = [];
    const path = (page) => new URL(page.url()).pathname;
    try {
      // The header's area control: a group named "Area" (X7), one item per offered area; the lit one is data-state=on.
      const control = (page) => page.getByRole('group', { name: 'Area' });
      const items = (page) => control(page).locator('button, [role=radio]');
      const areasOf = async (page) => (await items(page).allInnerTexts()).map((t) => t.trim());
      const lit = async (page) => (await control(page).locator('[data-state=on]').allInnerTexts()).map((t) => t.trim());
      // Rows of the sidebar's content: a row's own name, without a count or badge beside it.
      const rowsOf = async (page) => (await page.locator('[data-sidebar=header] a, [data-sidebar=content] a').allInnerTexts()).map((t) => t.split('\n')[0].trim()).filter(Boolean);
      // Settled: the sidebar has drawn a row and the cells have answered (no skeleton left).
      const settle = async (page) => {
        // At phone width the sidebar is a closed sheet with no links; the area button is what has drawn.
        await page.locator('[data-sidebar=header] a, [data-sidebar=content] a, button[aria-label^="Area: "]').first().waitFor({ timeout: 45_000 });
        await page.locator('[data-sidebar=content] [data-slot=skeleton]').first().waitFor({ state: 'detached', timeout: 30_000 }).catch(() => undefined);
        await page.waitForTimeout(700);
      };
      const open = async (page, p) => {
        await page.goto(`${consoleUrl}${p}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await settle(page);
      };
      const pick = async (page, area) => {
        if (!(await control(page).count())) throw new Error('no header control named Area');
        await items(page).filter({ hasText: area }).first().click();
        await control(page).locator('[data-state=on]').filter({ hasText: area }).waitFor({ timeout: 12_000 });
        await page.waitForTimeout(600);
      };
      const signedIn = async (email) => {
        const page = await consoleSignIn(browser, consoleUrl, email, PASSWORD, errors);
        page.setDefaultTimeout(12_000);
        return page;
      };
      const signOut = async (page) => {
        await page.locator('[data-sidebar=footer] [data-sidebar=menu-button]').first().click();
        await page.getByTestId('sign-out').click();
        await page.waitForURL((u) => u.pathname.startsWith('/login'));
      };
      const logIn = async (page, email) => {
        await page.getByLabel('Work email').fill(email);
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByTestId('login-submit').click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await settle(page);
      };
      const overlap = (rows, names) => names.filter((n) => rows.includes(n));

      await step('1 each person is offered the areas and pages their cells open, and no listed page refuses them', async () => {
        const seen = {};
        // Priya: admin of Operations. Wanjiru: admin of every team. James: a builder. Maya: a reviewer. Ravi: a viewer.
        const want = {
          [PRIYA]: { has: ['Policies', 'Reviews', 'Activity', 'Tool calls', 'Audit log', 'Evals', 'Model inventory', 'Access', 'Roles', 'Tool access', 'Settings'], lacks: ['Background'] },
          // Background needs an admin of every team: Priya is admin of Operations only, Wanjiru of all.
          [WANJIRU]: { has: ['Policies', 'Reviews', 'Activity', 'Tool calls', 'Audit log', 'Background', 'Evals', 'Model inventory', 'Access', 'Roles', 'Tool access', 'Settings'], lacks: [] },
          [JAMES]: { has: ['Reviews', 'Activity', 'Tool calls', 'Audit log', 'Evals', 'Access'], lacks: ['Policies', 'Settings', 'Background'] },
          [MAYA]: { has: ['Reviews', 'Activity', 'Tool calls', 'Evals', 'Access'], lacks: ['Audit log', 'Policies', 'Settings', 'Background'] },
          [RAVI]: { has: ['Access'], lacks: ['Activity', 'Tool calls', 'Audit log', 'Evals', 'Policies', 'Settings', 'Background'] },
        };
        let ok = true;
        for (const [email, w] of Object.entries(want)) {
          const page = await signedIn(email);
          const refused = [];
          page.on('response', (r) => {
            if (r.status() === 403 && !new URL(r.url()).pathname.includes('/me/')) refused.push(`${r.status()} ${new URL(r.url()).pathname}`);
          });
          await settle(page);
          const areas = await areasOf(page);
          await pick(page, 'Govern');
          const govern = await rowsOf(page);
          // Every area's rows open without a refusal (PERM-2): a listed page must answer for the person it is listed to.
          for (const area of AREAS) {
            if (!areas.includes(area)) continue;
            await pick(page, area);
            for (const href of await page.locator('[data-sidebar=content] a').evaluateAll((as) => as.map((a) => a.getAttribute('href')).filter((h) => h && h.startsWith('/') && !h.startsWith('/chat/')))) {
              await page.goto(`${consoleUrl}${href}`, { waitUntil: 'domcontentloaded' });
              await page.waitForTimeout(900);
            }
          }
          seen[email] = { areas, missing: w.has.filter((n) => !govern.includes(n)), extra: overlap(govern, w.lacks), refused: [...new Set(refused)] };
          ok = ok && JSON.stringify(areas) === JSON.stringify(AREAS) && seen[email].missing.length === 0 && seen[email].extra.length === 0 && seen[email].refused.length === 0;
          if (email === PRIYA || email === RAVI) await page.screenshot({ path: join(SHOTS, `govern-${email[0]}-1440.png`) });
          await page.context().close();
        }
        check('1 each person is offered the areas and pages their cells open, and no listed page refuses them', ok, seen);
      });

      await step('2 a chat-only person sees no area control at any width, lands on Chat, and is refused a page by its own message', async () => {
        const page = await signedIn(LENA);
        await settle(page);
        const landed = path(page);
        const rows = await rowsOf(page);
        const wide = (await control(page).count()) + (await page.getByRole('button', { name: /^Area:/ }).count());
        await page.setViewportSize({ width: 390, height: 844 });
        await page.waitForTimeout(500);
        const narrow = (await control(page).count()) + (await page.getByRole('button', { name: /^Area:/ }).count());
        await page.setViewportSize({ width: 1440, height: 1000 });
        await page.goto(`${consoleUrl}/`, { waitUntil: 'domcontentloaded' });
        await page.waitForURL((u) => u.pathname === '/chat', { timeout: 30_000 }).catch(() => undefined);
        const home = path(page);
        await page.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded' });
        await settle(page);
        const refusedRows = await rowsOf(page);
        await page.keyboard.press('ControlOrMeta+3');
        await page.waitForTimeout(500);
        await page.screenshot({ path: join(SHOTS, 'chat-only-1440.png') });
        const stayed = path(page);
        const need = ['New chat', 'All chats'];
        const none = ['Cases', 'Agents', 'Knowledge bases', 'Activity', 'Settings'];
        check(
          '2 a chat-only person sees no area control at any width, lands on Chat, and is refused a page by its own message',
          landed === '/chat' && wide === 0 && narrow === 0 && home === '/chat' && need.every((n) => rows.includes(n)) && none.every((n) => !rows.includes(n)) && JSON.stringify(refusedRows) === JSON.stringify(rows) && stayed === '/agents' && (await lit(page)).length === 0,
          { landed, wide, narrow, home, rows, refusedRows, stayed },
        );
        await page.context().close();
      });

      await step('3 a person in two teams is offered what each team opens, and the remembered area gives way where it is not offered', async () => {
        const page = await signedIn(TOMAS);
        await settle(page);
        const inOps = await areasOf(page);
        await pick(page, 'Build');
        const team = async (name) => {
          await page.getByRole('button', { name: /^Team: .*Switch team/ }).click();
          await page.getByRole('menuitem', { name: new RegExp(name) }).click();
          await page.waitForTimeout(1500);
          await settle(page);
        };
        await team('Platform');
        const inPlatform = { control: await control(page).count(), rows: await rowsOf(page) };
        await page.screenshot({ path: join(SHOTS, 'two-teams-platform-1440.png') });
        await team('Operations');
        const back = await areasOf(page);
        check(
          '3 a person in two teams is offered what each team opens, and the remembered area gives way where it is not offered',
          inOps.length >= 2 && inPlatform.control === 0 && inPlatform.rows.includes('New chat') && !inPlatform.rows.includes('Agents') && back.length === inOps.length,
          { inOps, inPlatform, back },
        );
        await page.context().close();
      });

      const priya = await signedIn(PRIYA);
      await settle(priya);

      await step('4 a chord opens the last page visited in that area, else its first row, and lights the area', async () => {
        await open(priya, '/cases');
        await priya.keyboard.press('ControlOrMeta+2');
        await priya.waitForURL((u) => u.pathname === '/agents', { timeout: 15_000 }).catch(() => undefined);
        const build = { url: path(priya), lit: await lit(priya), rows: await rowsOf(priya) };
        await priya.keyboard.press('ControlOrMeta+1');
        await priya.waitForURL((u) => u.pathname === '/cases', { timeout: 15_000 }).catch(() => undefined);
        const work = { url: path(priya), lit: await lit(priya) };
        await priya.keyboard.press('ControlOrMeta+k');
        const search = await priya.getByPlaceholder(/^Search /).first().isVisible().catch(() => false);
        await priya.keyboard.press('Escape');
        check('4 a chord opens the last page visited in that area, else its first row, and lights the area', build.url === '/agents' && build.lit[0] === 'Build' && build.rows.includes('Agents') && !build.rows.includes('Cases') && work.url === '/cases' && work.lit[0] === 'Work' && search, { build, work, search });
      });

      await step('5 a chord does nothing while a field or a dialog has focus', async () => {
        // The same chord first works with nothing focused, so "nothing happens" below cannot be a chord that never works.
        await open(priya, '/chat');
        await priya.locator('body').click({ position: { x: 5, y: 5 } }).catch(() => undefined);
        await priya.keyboard.press('ControlOrMeta+2');
        const works = await priya.waitForURL((u) => u.pathname !== '/chat', { timeout: 8_000 }).then(() => true, () => false);
        await open(priya, '/chat');
        const box = priya.getByRole('textbox', { name: 'Message' }).first();
        await box.waitFor();
        await box.focus();
        await priya.keyboard.press('ControlOrMeta+2');
        await priya.waitForTimeout(600);
        const inField = path(priya);
        await priya.keyboard.press('Escape');
        await priya.locator('body').click({ position: { x: 5, y: 5 } }).catch(() => undefined);
        await priya.keyboard.press('ControlOrMeta+k');
        await priya.getByPlaceholder(/^Search /).first().waitFor();
        await priya.keyboard.press('ControlOrMeta+3');
        await priya.waitForTimeout(600);
        const inDialog = path(priya);
        await priya.keyboard.press('Escape');
        check('5 a chord does nothing while a field or a dialog has focus', works && inField === '/chat' && inDialog === '/chat', { works, inField, inDialog });
      });

      await step('6 search lists each page once under its area, only pages the person may open, and a pick lights its area', async () => {
        await open(priya, '/chat');
        await priya.keyboard.press('ControlOrMeta+k');
        const dialog = priya.getByPlaceholder(/^Search /).first();
        await dialog.waitFor();
        await dialog.fill('knowledge');
        await priya.getByRole('option', { name: /Knowledge bases/ }).first().waitFor({ timeout: 15_000 });
        await dialog.fill('');
        const headings = await priya.locator('[cmdk-group-heading]').allInnerTexts();
        const names = (await priya.getByRole('option').allInnerTexts()).map((t) => t.split('\n')[0].trim());
        const twice = names.filter((n, i) => names.indexOf(n) !== i);
        await dialog.fill('knowledge');
        await priya.getByRole('option', { name: /Knowledge bases/ }).first().click();
        await priya.waitForURL((u) => u.pathname.startsWith('/knowledge'), { timeout: 30_000 });
        await settle(priya);
        const picked = { lit: await lit(priya), rows: await rowsOf(priya) };
        // A viewer is not offered Activity in search.
        const ravi = await signedIn(RAVI);
        await settle(ravi);
        await ravi.keyboard.press('ControlOrMeta+k');
        const search = ravi.getByPlaceholder(/^Search /).first();
        await search.waitFor();
        await search.fill('activity');
        await ravi.waitForTimeout(600);
        const raviSees = (await ravi.getByRole('option').allInnerTexts()).map((t) => t.split('\n')[0].trim());
        await ravi.context().close();
        check(
          '6 search lists each page once under its area, only pages the person may open, and a pick lights its area',
          AREAS.every((a) => headings.some((h) => h.includes(a))) && twice.length === 0 && picked.lit[0] === 'Data' && picked.rows.includes('Knowledge bases') && !raviSees.some((n) => /^(Activity|Tool calls)$/.test(n)),
          { headings, twice, picked, raviSees },
        );
      });

      await step('7 the remembered area belongs to the person, not the browser', async () => {
        const page = await signedIn(JAMES);
        await settle(page);
        await pick(page, 'Build');
        await signOut(page);
        await logIn(page, PRIYA);
        // Priya has no area of her own yet: she lands on Work, not on James's Build.
        const first = await lit(page);
        await pick(page, 'Govern');
        await signOut(page);
        await logIn(page, JAMES);
        const james = await lit(page);
        await signOut(page);
        await logIn(page, PRIYA);
        await open(page, '/chat');
        const priyaAgain = { lit: await lit(page), rows: await rowsOf(page) };
        check('7 the remembered area belongs to the person, not the browser', first[0] === 'Work' && james[0] === 'Build' && priyaAgain.lit[0] === 'Govern' && priyaAgain.rows.includes('Audit log'), { first, james, priyaAgain });
        await page.context().close();
      });

      await step('8 a page reached by link lights its own area, and the trail names it', async () => {
        const seen = {};
        const routes = [['/deployments', 'Build'], ['/prompt-blocks', 'Build'], ['/sources', 'Data'], ['/wiki', 'Data'], ['/connect', 'Build'], ['/reviews/all', 'Govern']];
        for (const [route, area] of routes) {
          await priya.goto(`${consoleUrl}${route}`, { waitUntil: 'domcontentloaded' });
          await settle(priya);
          const crumbs = await priya.locator('header nav[aria-label=Breadcrumb] > span').count();
          seen[route] = { lit: (await lit(priya))[0], crumbs };
        }
        check('8 a page reached by link lights its own area, and the trail names it', routes.every(([r, a]) => seen[r].lit === a && seen[r].crumbs > 0), seen);
      });

      await step('9 on a phone one 44 px button replaces the area control, a pick opens that area, and the sheet lists only it', async () => {
        const page = await signedIn(PRIYA);
        await page.setViewportSize({ width: 390, height: 844 });
        await open(page, '/agents');
        const button = page.getByRole('button', { name: /^Area: Build\. Switch area/ });
        await button.waitFor({ timeout: 12_000 });
        const box = await button.boundingBox();
        const group = await control(page).count();
        await page.screenshot({ path: join(SHOTS, 'phone-390.png') });
        await button.click();
        await page.getByRole('menuitem', { name: /Data/ }).click();
        await page.waitForTimeout(800);
        const menuClosed = (await page.getByRole('menu').count()) === 0;
        const moved = path(page);
        const label = await page.getByRole('button', { name: /^Area: / }).first().getAttribute('aria-label');
        await page.locator('[data-slot=sidebar-trigger]').first().click();
        const sheet = page.locator('[data-slot=sidebar][data-mobile=true]');
        await sheet.waitFor({ timeout: 15_000 });
        const rows = (await sheet.locator('[data-sidebar=content] a').allInnerTexts()).map((t) => t.split('\n')[0].trim());
        await sheet.getByRole('link', { name: 'Knowledge bases' }).click();
        await page.waitForTimeout(800);
        const closed = (await page.locator('[data-slot=sidebar][data-mobile=true]').count()) === 0;
        const wide = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        check('9 on a phone one 44 px button replaces the area control, a pick opens that area, and the sheet lists only it', !!box && box.height >= 44 && group === 0 && menuClosed && !moved.startsWith('/agents') && /Data/.test(label ?? '') && rows.includes('Knowledge bases') && !rows.includes('Agents') && closed && !wide, { height: box?.height, group, menuClosed, moved, label, rows, closed, wide });
        await page.context().close();
      });

      await step('10 the longest trail fits at 1024 and the control stays where the sidebar folds', async () => {
        await priya.setViewportSize({ width: 1024, height: 900 });
        await open(priya, '/tools/calls');
        const fit = await priya.evaluate(() => ({
          sideways: document.documentElement.scrollWidth > window.innerWidth,
          cut: [...document.querySelectorAll('[role=group][aria-label=Area] :is(button,[role=radio])')].filter((b) => b.scrollWidth > b.clientWidth).length,
        }));
        const shown = await items(priya).count();
        const before = await lit(priya);
        await priya.setViewportSize({ width: 1440, height: 1000 });
        await open(priya, '/chat');
        const sidebar = priya.locator('[data-slot=sidebar]').first();
        if ((await sidebar.getAttribute('data-state')) !== 'collapsed') await priya.locator('[data-slot=sidebar-trigger]').first().click();
        await priya.waitForTimeout(500);
        const folded = { state: await sidebar.getAttribute('data-state'), lit: await lit(priya), shown: await items(priya).count() };
        await priya.screenshot({ path: join(SHOTS, 'folded-1440.png') });
        await priya.locator('[data-slot=sidebar-trigger]').first().click();
        check('10 the longest trail fits at 1024 and the control stays where the sidebar folds', !fit.sideways && fit.cut === 0 && shown === 4 && folded.state === 'collapsed' && before[0] === 'Govern' && folded.lit[0] === before[0] && folded.shown === 4, { fit, shown, before, folded });
      });

      await step('11 the control is named, exposes what is lit, and works from the keyboard', async () => {
        await open(priya, '/agents');
        const state = await items(priya).evaluateAll((els) => els.map((e) => e.getAttribute('aria-pressed') ?? e.getAttribute('aria-checked')));
        const named = await control(priya).count();
        await items(priya).filter({ hasText: 'Build' }).first().focus();
        await priya.keyboard.press('ArrowRight');
        const focused = await priya.evaluate(() => document.activeElement?.textContent?.trim());
        await priya.keyboard.press('Enter');
        await priya.waitForURL((u) => !u.pathname.startsWith('/agents'), { timeout: 15_000 }).catch(() => undefined);
        await settle(priya);
        const afterKey = await lit(priya);
        // Clicking the lit button again keeps it lit.
        await pick(priya, 'Data');
        await items(priya).filter({ hasText: 'Data' }).first().click();
        await priya.waitForTimeout(500);
        const stays = await lit(priya);
        check('11 the control is named, exposes what is lit, and works from the keyboard', named === 1 && state.every((s) => s === 'true' || s === 'false') && state.filter((s) => s === 'true').length === 1 && focused === 'Data' && afterKey[0] === 'Data' && stays[0] === 'Data', { named, state, focused, afterKey, stays });
      });

      await step('12 while cells load there are skeleton rows and no control; when they fail there is one way to try again', async () => {
        const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
        const page = await context.newPage();
        page.setDefaultTimeout(15_000);
        let mode = 'pass';
        let release;
        const held = new Promise((r) => (release = r));
        await page.route((u) => u.pathname.endsWith('/v1/me/permissions'), async (route) => {
          if (mode === 'slow') await held;
          if (mode === 'fail') return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ error: { code: 'internal', message: 'down' } }) });
          return route.continue();
        });
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded' });
        await page.getByLabel('Work email').fill(RAVI);
        await page.getByLabel('Password').fill(PASSWORD);
        mode = 'slow';
        await page.getByTestId('login-submit').click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await page.waitForTimeout(1500);
        const slow = { skeletons: await page.locator('[data-sidebar=content] [data-slot=skeleton]').count(), control: await control(page).count() };
        await page.screenshot({ path: join(SHOTS, 'cells-slow-1440.png') });
        release();
        await control(page).waitFor({ timeout: 30_000 });
        const counts = [];
        for (let i = 0; i < 3; i++) {
          counts.push(await items(page).count());
          await page.waitForTimeout(400);
        }
        mode = 'fail';
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.getByText('Pages unavailable').first().waitFor({ timeout: 12_000 });
        const failed = { retry: await page.getByText('Try again').count(), control: await control(page).count(), trigger: await page.locator('[data-slot=sidebar-trigger]').count() };
        await page.screenshot({ path: join(SHOTS, 'cells-error-1440.png') });
        mode = 'pass';
        await page.getByText('Try again').first().click();
        await control(page).waitFor({ timeout: 30_000 });
        check('12 while cells load there are skeleton rows and no control; when they fail there is one way to try again', slow.skeletons > 0 && slow.control === 0 && new Set(counts).size === 1 && counts[0] === 4 && failed.retry >= 1 && failed.control === 0 && failed.trigger >= 1, { slow, counts, failed });
        await context.close();
      });

      await step('13 inside Settings the settings sidebar stays, Govern stays lit, and Back returns to the remembered area', async () => {
        await open(priya, '/activity');
        await open(priya, '/settings');
        const inside = { lit: await lit(priya), back: await priya.getByRole('link', { name: 'Back to the console' }).count(), find: await priya.getByLabel('Find a setting').count() };
        await priya.screenshot({ path: join(SHOTS, 'settings-1440.png') });
        await priya.getByRole('link', { name: 'Back to the console' }).click();
        await priya.waitForURL((u) => !u.pathname.startsWith('/settings'), { timeout: 30_000 });
        await settle(priya);
        const back = { url: path(priya), lit: await lit(priya) };
        check('13 inside Settings the settings sidebar stays, Govern stays lit, and Back returns to the remembered area', inside.lit[0] === 'Govern' && inside.back === 1 && inside.find === 1 && back.lit[0] === 'Govern', { inside, back });
      });

      await step('14 an old address answers one redirect to its page, and Policies has its own page', async () => {
        const hop = async (from) => {
          const r = await priya.request.get(`${consoleUrl}${from}`, { maxRedirects: 0 });
          return { status: r.status(), to: r.headers().location ? new URL(r.headers().location, consoleUrl).pathname : null };
        };
        const seen = { calls: await hop('/logs/tool-calls'), policies: await hop('/settings/policies'), account: await hop('/account') };
        // /policies is a page of its own in Govern; a 404 has no sidebar, so this reads the page without waiting for one.
        await priya.goto(`${consoleUrl}/policies`, { waitUntil: 'domcontentloaded' });
        await priya.waitForTimeout(2000);
        const policies = { url: path(priya), lit: await lit(priya), rows: await rowsOf(priya) };
        check(
          '14 an old address answers one redirect to its page, and Policies has its own page',
          seen.calls.status === 307 && seen.calls.to === '/tools/calls' && seen.policies.status === 307 && seen.policies.to === '/policies' && seen.account.status === 307 && seen.account.to === '/settings/account' && policies.lit[0] === 'Govern' && policies.rows.includes('Policies'),
          { seen, policies },
        );
      });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);
finish();
