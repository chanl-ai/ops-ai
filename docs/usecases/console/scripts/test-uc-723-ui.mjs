// uc-723 the console lists every area as an open sidebar section; the area tabs come back with the area_tabs flag, ui
// layer: docs/usecases/console/console-areas.md. Headless Chromium on the demo stack, signed in through platform-service as
// the seeded people (services/platform-service/seed/people.json) and the fixtures added for this card: Lena (chat only)
// and Tomas (a builder in Operations, a chat user in Platform). Nothing names a role: what a person is offered is what
// their cells open. Steps 1 to 15 run on an install with no flags; step 16 runs a second stack with OPS_FLAGS=area_tabs.
// Screenshots go to evidenceDir('723', 'uc').
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
// The sidebar's sections, in order, for a person whose cells open a page in every area: one link per page, no sub-rows.
const SECTIONS = ['Work', 'Agent Builder', 'Data Gateway', 'Governance'];
const sectionsRight = (labels) => JSON.stringify(labels) === JSON.stringify(SECTIONS);
// The areas the search groups name; the area tabs (flag area_tabs) use the section names above.
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

async function walk(consoleUrl, browser, errors, mode) {
  mkdirSync(SHOTS, { recursive: true });
  const path = (page) => new URL(page.url()).pathname;
  // The area tabs (flag area_tabs): a group named "Area", one item per offered area; the lit one is data-state=on.
  const control = (page) => page.getByRole('group', { name: 'Area' });
  const items = (page) => control(page).locator('button, [role=radio]');
  const lit = async (page) => (await control(page).locator('[data-state=on]').allInnerTexts()).map((t) => t.trim());
  // Rows of the sidebar's content: a row's own name, without a count or badge beside it.
  const rowsOf = async (page) => (await page.locator('[data-sidebar=header] a, [data-sidebar=content] a').allInnerTexts()).map((t) => t.split('\n')[0].trim()).filter(Boolean);
  // The one sidebar: each open section's heading and its rows (Chat is a link in Work; its list of chats is a column on the chat pages).
  const sectionsOf = async (page) =>
    page.evaluate(() =>
      [...document.querySelectorAll('[data-sidebar=content] [data-nav-group]')]
        .map((g) => ({ label: g.getAttribute('data-nav-group'), rows: [...g.querySelectorAll('a')].map((a) => a.innerText.split('\n')[0].trim()) })),
    );
  // The row lit for the page, and the section it sits in.
  const litRow = async (page) =>
    page.evaluate(() => {
      const a = document.querySelector('[data-sidebar=content] [data-active=true]');
      return a ? { row: a.innerText.split('\n')[0].trim(), section: a.closest('[data-nav-group]')?.getAttribute('data-nav-group') ?? null } : null;
    });
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
  const signedIn = async (email) => {
    const page = await consoleSignIn(browser, consoleUrl, email, PASSWORD, errors);
    page.setDefaultTimeout(12_000);
    return page;
  };
  const overlap = (rows, names) => names.filter((n) => rows.includes(n));
  const names = (secs) => secs.map((s) => s.label);

  if (mode === 'tabs') {
    await step('16 with area_tabs on the tabs come back: four areas, a chord switches the sidebar to one area, a phone gets one button', async () => {
      const page = await signedIn(PRIYA);
      await settle(page);
      const areas = (await items(page).allInnerTexts()).map((t) => t.trim());
      // With the tabs on no area is a section heading (the Chats list under Work is not one).
      const oneSidebar = names(await sectionsOf(page)).filter((l) => SECTIONS.includes(l));
      await open(page, '/work/cases');
      await page.keyboard.press('ControlOrMeta+2');
      await page.waitForURL((u) => u.pathname === '/build/agents', { timeout: 15_000 }).catch(() => undefined);
      const build = { url: path(page), lit: await lit(page), rows: await rowsOf(page) };
      await page.screenshot({ path: join(SHOTS, 'area-tabs-build-1440.png') });
      await page.keyboard.press('ControlOrMeta+1');
      await page.waitForURL((u) => u.pathname === '/work/cases', { timeout: 15_000 }).catch(() => undefined);
      const work = { url: path(page), lit: await lit(page) };
      await page.setViewportSize({ width: 390, height: 844 });
      await open(page, '/build/agents');
      const button = page.getByRole('button', { name: /^Area: Agent Builder\. Switch area/ });
      await button.waitFor({ timeout: 12_000 });
      const box = await button.boundingBox();
      check(
        '16 with area_tabs on the tabs come back: four areas, a chord switches the sidebar to one area, a phone gets one button',
        JSON.stringify(areas) === JSON.stringify(SECTIONS) && oneSidebar.length === 0 && build.url === '/build/agents' && build.lit[0] === 'Agent Builder' && build.rows.includes('Agents') && !build.rows.includes('Cases') && work.url === '/work/cases' && work.lit[0] === 'Work' && !!box && box.height >= 44,
        { areas, oneSidebar, build, work, height: box?.height },
      );
      await page.context().close();
    });
    return;
  }

  await step('1 each person is offered the four sections and the pages their cells open, all open, and no listed page refuses them', async () => {
    const seen = {};
    // Priya: admin of Operations. Wanjiru: admin of every team. James: a builder. Maya: a reviewer. Ravi: a viewer.
    const want = {
      [PRIYA]: { has: ['Policies', 'Reviews', 'Activity', 'Evals', 'Access', 'Settings'], lacks: ['Background'] },
      // Background needs an admin of every team: Priya is admin of Operations only, Wanjiru of all.
      [WANJIRU]: { has: ['Policies', 'Reviews', 'Activity', 'Evals', 'Access', 'Settings'], lacks: [] },
      [JAMES]: { has: ['Reviews', 'Activity', 'Evals', 'Access'], lacks: ['Policies', 'Settings', 'Background'] },
      [MAYA]: { has: ['Reviews', 'Activity', 'Evals', 'Access'], lacks: ['Audit log', 'Policies', 'Settings', 'Background'] },
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
      const secs = await sectionsOf(page);
      const governance = secs.find((s) => s.label === 'Governance')?.rows ?? [];
      // Nothing is folded: no row hides its pages behind an arrow, and no area control is drawn.
      const folds = await page.getByRole('button', { name: /^Show .+ pages$/ }).count();
      const tabs = await control(page).count();
      // Every listed row opens without a refusal (PERM-2): a listed page must answer for the person it is listed to.
      for (const href of await page.locator('[data-sidebar=content] a').evaluateAll((as) => [...new Set(as.map((a) => a.getAttribute('href')).filter((h) => h && h.startsWith('/') && !h.startsWith('/chat/')))])) {
        await page.goto(`${consoleUrl}${href}`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(900);
      }
      seen[email] = { sections: names(secs), missing: w.has.filter((n) => !governance.includes(n)), extra: overlap(governance, w.lacks), folds, tabs, refused: [...new Set(refused)] };
      ok = ok && sectionsRight(names(secs)) && seen[email].missing.length === 0 && seen[email].extra.length === 0 && folds === 0 && tabs === 0 && seen[email].refused.length === 0;
      if (email === PRIYA || email === RAVI) await page.screenshot({ path: join(SHOTS, `sections-${email[0]}-1440.png`) });
      await page.context().close();
    }
    check('1 each person is offered the four sections and the pages their cells open, all open, and no listed page refuses them', ok, seen);
  });

  await step('2 a chat-only person sees only Work with Chat in it and no area control at any width, lands on Chat, and is refused a page by its own message', async () => {
    const page = await signedIn(LENA);
    await settle(page);
    const landed = path(page);
    const rows = await rowsOf(page);
    const sections = names(await sectionsOf(page));
    const wide = (await control(page).count()) + (await page.getByRole('button', { name: /^Area:/ }).count());
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(500);
    const narrow = (await control(page).count()) + (await page.getByRole('button', { name: /^Area:/ }).count());
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`${consoleUrl}/overview`, { waitUntil: 'domcontentloaded' });
    await page.waitForURL((u) => u.pathname === '/chat', { timeout: 30_000 }).catch(() => undefined);
    const home = path(page);
    await page.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded' });
    await settle(page);
    const refusedRows = await rowsOf(page);
    await page.screenshot({ path: join(SHOTS, 'chat-only-1440.png') });
    const stayed = path(page);
    const need = ['New chat', 'Chat'];
    const none = ['Cases', 'Agents', 'Knowledge bases', 'Activity', 'Settings'];
    check(
      '2 a chat-only person sees only Work with Chat in it and no area control at any width, lands on Chat, and is refused a page by its own message',
      landed === '/chat' && JSON.stringify(sections) === JSON.stringify(['Work']) && wide === 0 && narrow === 0 && home === '/chat' && need.every((n) => rows.includes(n)) && none.every((n) => !rows.includes(n)) && none.every((n) => !refusedRows.includes(n)) && refusedRows.includes('New chat') && stayed.endsWith('/agents') && (await litRow(page)) === null,
      { landed, sections, wide, narrow, home, rows, refusedRows, stayed },
    );
    await page.context().close();
  });

  await step('3 a person in two teams is offered the sections each team opens', async () => {
    const page = await signedIn(TOMAS);
    await settle(page);
    const inOps = names(await sectionsOf(page));
    const team = async (name) => {
      await page.getByRole('button', { name: /^Team: .*Switch team/ }).click();
      await page.getByRole('menuitem', { name: new RegExp(name) }).click();
      await page.waitForTimeout(1500);
      await settle(page);
    };
    await team('Platform');
    const inPlatform = { sections: names(await sectionsOf(page)), rows: await rowsOf(page) };
    await page.screenshot({ path: join(SHOTS, 'two-teams-platform-1440.png') });
    await team('Operations');
    const back = names(await sectionsOf(page));
    check(
      '3 a person in two teams is offered the sections each team opens',
      inOps.length >= 2 && JSON.stringify(inPlatform.sections) === JSON.stringify(['Work']) && inPlatform.rows.includes('New chat') && !inPlatform.rows.includes('Agents') && JSON.stringify(back) === JSON.stringify(inOps),
      { inOps, inPlatform, back },
    );
    await page.context().close();
  });

  const priya = await signedIn(PRIYA);
  await settle(priya);

  await step('4 a person on any page sees every section at once, the row for the page lit in its own section, and no chord switches anything', async () => {
    await open(priya, '/work/cases');
    const before = { secs: names(await sectionsOf(priya)), lit: await litRow(priya) };
    await priya.keyboard.press('ControlOrMeta+2');
    await priya.waitForTimeout(800);
    const after = { url: path(priya), tabs: await control(priya).count(), secs: names(await sectionsOf(priya)) };
    await open(priya, '/build/agents');
    const agents = await litRow(priya);
    await priya.screenshot({ path: join(SHOTS, 'sections-agents-1440.png') });
    check(
      '4 a person on any page sees every section at once, the row for the page lit in its own section, and no chord switches anything',
      sectionsRight(before.secs) && before.lit?.row === 'Cases' && before.lit.section === 'Work' && after.url === '/work/cases' && after.tabs === 0 && sectionsRight(after.secs) && agents?.row === 'Agents' && agents.section === 'Agent Builder',
      { before, after, agents },
    );
  });

  await step('6 search lists each page once under its area, only pages the person may open, and a pick lights its row in the Data Gateway section', async () => {
    await open(priya, '/chat');
    await priya.keyboard.press('ControlOrMeta+k');
    const dialog = priya.getByPlaceholder(/^Search /).first();
    await dialog.waitFor();
    await dialog.fill('knowledge');
    await priya.getByRole('option', { name: /Knowledge bases/ }).first().waitFor({ timeout: 15_000 });
    await dialog.fill('');
    const headings = await priya.locator('[cmdk-group-heading]').allInnerTexts();
    const found = (await priya.getByRole('option').allInnerTexts()).map((t) => t.split('\n')[0].trim());
    const twice = found.filter((n, i) => found.indexOf(n) !== i);
    await dialog.fill('knowledge');
    await priya.getByRole('option', { name: /Knowledge bases/ }).first().click();
    await priya.waitForURL((u) => u.pathname.startsWith('/data/knowledge'), { timeout: 30_000 });
    await settle(priya);
    const picked = await litRow(priya);
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
      '6 search lists each page once under its area, only pages the person may open, and a pick lights its row in the Data Gateway section',
      AREAS.every((a) => headings.some((h) => h.includes(a))) && twice.length === 0 && /^Knowledge/.test(picked?.row ?? '') && picked.section === 'Data Gateway' && !raviSees.some((n) => /^(Activity|Tool calls)$/.test(n)),
      { headings, twice, picked, raviSees },
    );
  });

  await step('8 a page reached by an old link lights its row in the right section, and the trail draws', async () => {
    const seen = {};
    const routes = [['/deployments', /^Channels$/, /^Agent Builder$/], ['/prompt-blocks', /^Skills$/, /^Agent Builder$/], ['/sources', /^(Connectors|Apps)$/, /^Data Gateway$/], ['/wiki', /^Knowledge/, /^Data Gateway$/], ['/connect', /^Channels$/, /^Agent Builder$/], ['/reviews/all', /^Reviews$/, /^Governance$/]];
    for (const [route] of routes) {
      await priya.goto(`${consoleUrl}${route}`, { waitUntil: 'domcontentloaded' });
      await settle(priya);
      const crumbs = await priya.locator('header nav[aria-label=Breadcrumb] > span').count();
      seen[route] = { lit: await litRow(priya), crumbs };
    }
    check('8 a page reached by an old link lights its row in the right section, and the trail draws', routes.every(([r, row, section]) => row.test(seen[r].lit?.row ?? '') && section.test(seen[r].lit?.section ?? '') && seen[r].crumbs > 0), seen);
  });

  await step('12 while cells load there are skeleton rows and no sections; when they fail there is one way to try again', async () => {
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
    const slow = { skeletons: await page.locator('[data-sidebar=content] [data-slot=skeleton]').count(), sections: (await sectionsOf(page)).length };
    await page.screenshot({ path: join(SHOTS, 'cells-slow-1440.png') });
    release();
    await page.locator('[data-sidebar=content] [data-nav-group="Governance"]').waitFor({ timeout: 30_000 });
    const counts = [];
    for (let i = 0; i < 3; i++) {
      counts.push((await sectionsOf(page)).length);
      await page.waitForTimeout(400);
    }
    mode = 'fail';
    await page.reload({ waitUntil: 'domcontentloaded' });
    // The sidebar starts folded, so the retry row is its icon button, named for what it does.
    const retry = page.getByRole('button', { name: 'Pages unavailable. Try again' });
    await retry.waitFor({ timeout: 12_000 });
    const failed = { retry: await retry.count(), sections: (await sectionsOf(page)).length, trigger: await page.locator('[data-slot=sidebar-trigger]').count() };
    await page.screenshot({ path: join(SHOTS, 'cells-error-1440.png') });
    mode = 'pass';
    await retry.click();
    await page.locator('[data-sidebar=content] [data-nav-group="Governance"]').waitFor({ timeout: 30_000 });
    check('12 while cells load there are skeleton rows and no sections; when they fail there is one way to try again', slow.skeletons > 0 && slow.sections === 0 && new Set(counts).size === 1 && counts[0] >= SECTIONS.length && failed.retry >= 1 && failed.sections === 0 && failed.trigger >= 1, { slow, counts, failed });
    await context.close();
  });

  await step('13 inside Settings the settings sidebar stays, and Back returns to the page and the sections', async () => {
    await open(priya, '/govern/activity');
    await open(priya, '/settings');
    const inside = { back: await priya.getByRole('link', { name: 'Back to the console' }).count(), find: await priya.getByLabel('Find a setting').count() };
    await priya.screenshot({ path: join(SHOTS, 'settings-1440.png') });
    await priya.getByRole('link', { name: 'Back to the console' }).click();
    await priya.waitForURL((u) => !u.pathname.startsWith('/settings'), { timeout: 30_000 });
    await settle(priya);
    const back = { url: path(priya), sections: names(await sectionsOf(priya)) };
    check('13 inside Settings the settings sidebar stays, and Back returns to the page and the sections', inside.back === 1 && inside.find === 1 && sectionsRight(back.sections), { inside, back });
  });

  await step('14 an old address answers one redirect to its page, and Policies has its own page in Governance', async () => {
    const hop = async (from) => {
      const r = await priya.request.get(`${consoleUrl}${from}`, { maxRedirects: 0 });
      return { status: r.status(), to: r.headers().location ? new URL(r.headers().location, consoleUrl).pathname : null };
    };
    const seen = { calls: await hop('/logs/tool-calls'), policies: await hop('/settings/policies'), account: await hop('/account') };
    // /policies is a page of its own in Governance; a 404 has no sidebar, so this reads the page without waiting for one.
    await priya.goto(`${consoleUrl}/policies`, { waitUntil: 'domcontentloaded' });
    await priya.waitForTimeout(2000);
    const policies = { url: path(priya), lit: await litRow(priya) };
    check(
      '14 an old address answers one redirect to its page, and Policies has its own page in Governance',
      seen.calls.status === 307 && seen.calls.to === '/tools/calls' && seen.policies.status === 307 && seen.policies.to === '/policies' && seen.account.status === 307 && seen.account.to === '/settings/account' && policies.lit?.row === 'Policies' && policies.lit.section === 'Governance',
      { seen, policies },
    );
  });

  await step('15 no crumb is cut at 1440, and Policies reads as a trail ending in Policies', async () => {
    await priya.setViewportSize({ width: 1440, height: 1000 });
    const seen = {};
    // The settings trails are the longest (four crumbs), then a Governance child page.
    for (const route of ['/policies', '/settings/policies/gates', '/settings/security/egress', '/settings/workspace/model-providers', '/tools/calls', '/logs/background']) {
      await open(priya, route);
      seen[route] = await priya.evaluate(() => {
        const nav = document.querySelector('header nav[aria-label=Breadcrumb]');
        const labels = [...nav.querySelectorAll('a, span.truncate')];
        return { text: labels.map((e) => e.textContent.trim()), cut: labels.filter((e) => e.scrollWidth > e.clientWidth).map((e) => e.textContent.trim()) };
      });
    }
    await open(priya, '/policies');
    await priya.screenshot({ path: join(SHOTS, 'trail-policies-1440.png') });
    check('15 no crumb is cut at 1440, and Policies reads as a trail ending in Policies', Object.values(seen).every((v) => v.cut.length === 0) && seen['/policies'].text.at(-1) === 'Policies', seen);
  });

  await priya.context().close();
}

const errors = [];
const browser = await chromium.launch();
try {
  await withUiStack((consoleUrl) => walk(consoleUrl, browser, errors, 'default'), { platform: true, demo: true });
  check('no page errors', errors.length === 0, errors.slice(0, 3));
  // The area tabs are off until the install names the flag; a second stack turns them on.
  process.env.OPS_FLAGS = 'area_tabs';
  const tabErrors = [];
  await withUiStack((consoleUrl) => walk(consoleUrl, browser, tabErrors, 'tabs'), { platform: true, demo: true });
  check('no page errors with area_tabs on', tabErrors.length === 0, tabErrors.slice(0, 3));
} finally {
  await browser.close();
}
finish();
