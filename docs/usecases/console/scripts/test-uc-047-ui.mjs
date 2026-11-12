// uc-047 sub-pages show as rows in the sidebar, ui layer: docs/usecases/console/sub-pages-in-the-sidebar.md.
// Headless Chromium, signed in through platform-service; every parent with children lists them as indented rows.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

// The sidebar lists one area at a time (uc-721), so each section's sub-rows are read on the page of its own area.
// James is a builder: he holds audit: view but not access: manage, so his Activity section lists Tool calls and Audit log
// and no Background; Maya, a reviewer, holds neither audit: view nor Background.
const BUILD_CHILDREN = ['All workflows', 'Runs'];
const GOVERN_CHILDREN = ['Tool calls', 'Audit log', 'Roles', 'Tool access', 'Model inventory'];

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const nav = page.locator('[data-sidebar="sidebar"]');
      const subRows = nav.locator('[data-sidebar="menu-sub-button"]');
      // A row's own name; a Preview badge beside it is not part of it.
      const active = async () => (await nav.locator('[data-active="true"]').allInnerTexts()).map((t) => t.split('\n')[0].trim());
      const open = async (path) => {
        await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await nav.locator('[data-sidebar="menu-button"]').first().waitFor({ timeout: 120_000 });
        await page.waitForTimeout(800);
      };

      await open('/workflows');
      const listed = (await subRows.allInnerTexts()).map((t) => t.trim());
      check('every parent lists its sub-pages as sidebar rows, open by default, in its own area', JSON.stringify(listed) === JSON.stringify(BUILD_CHILDREN), listed);
      const otherAreas = await nav.getByRole('link', { name: /^(Cases|Knowledge bases|Activity)$/ }).count();
      check('the sidebar lists the current area only: no Work, Data or Govern row beside the Build rows', otherAreas === 0, otherAreas);
      check("on a one-child section's own page its own sub-row is the active one", JSON.stringify(await active()) === '["All workflows"]', await active());

      await open('/activity');
      const govern = (await subRows.allInnerTexts()).map((t) => t.trim());
      check('the Govern area lists its sections\' sub-pages as rows', GOVERN_CHILDREN.every((c) => govern.includes(c)) && !govern.includes('Runs'), govern);
      check("on a multi-child section's own page the parent row lights alone", JSON.stringify(await active()) === '["Activity"]', await active());

      await open('/workflows');
      await subRows.filter({ hasText: 'Runs' }).click();
      await page.waitForURL((u) => u.pathname === '/workflows/runs', { timeout: 60_000 });
      await page.waitForTimeout(800);
      check('a sub-row opens its page and is the only active row', JSON.stringify(await active()) === '["Runs"]', await active());

      await open('/activity');
      await nav.getByRole('button', { name: 'Hide Activity pages' }).click();
      await page.waitForTimeout(400);
      const hidden = !(await nav.getByText('Tool calls').isVisible());
      await open('/activity');
      const stillHidden = !(await nav.getByText('Tool calls').isVisible());
      check("a parent the viewer closes stays closed after a reload", hidden && stillHidden, { hidden, stillHidden });

      await open('/tools/calls');
      check(
        "a closed parent opens when one of its pages is the current page, with that row active",
        (await nav.getByText('Tool calls', { exact: true }).isVisible()) && JSON.stringify(await active()) === '["Tool calls"]',
        await active(),
      );

      await open('/workflows/runs');
      const switched = await (async () => {
        await page.getByTestId('title-switcher').click();
        const items = (await page.getByRole('menuitem').allInnerTexts()).map((t) => t.trim());
        await page.getByRole('menuitem', { name: 'All workflows' }).click();
        await page.waitForURL((u) => u.pathname === '/workflows', { timeout: 30_000 });
        return items;
      })().catch((e) => String(e));
      check(
        'the page-title switcher still lists the section and moves between its pages',
        JSON.stringify(switched) === '["All workflows","Runs"]',
        switched,
      );

      // The audit log row follows the audit: view cell: a builder holds it, a reviewer does not.
      const maya = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      await maya.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByLabel('Email').fill('m.okafor@harborpine.example');
      await maya.getByLabel('Password').fill('northfield-demo');
      await maya.getByRole('button', { name: /^Sign in/ }).first().click();
      await maya.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await maya.goto(`${consoleUrl}/activity`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const mayaRows = maya.locator('[data-sidebar="sidebar"] [data-sidebar="menu-sub-button"]');
      await mayaRows.first().waitFor({ timeout: 60_000 });
      await maya.waitForTimeout(1_500);
      const mayaSees = (await mayaRows.allInnerTexts()).map((t) => t.trim());
      check('the audit log row shows to a builder and not to a reviewer', govern.includes('Audit log') && !mayaSees.includes('Audit log') && mayaSees.includes('Tool calls'), { builder: govern, reviewer: mayaSees });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
