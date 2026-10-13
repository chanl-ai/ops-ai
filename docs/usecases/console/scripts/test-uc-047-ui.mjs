// uc-047 sub-pages show as rows in the sidebar, ui layer: docs/usecases/console/sub-pages-in-the-sidebar.md.
// Headless Chromium, signed in through platform-service; every parent with children lists them as indented rows.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

// A section with one child also lists its own page as a sub-row, so the lone child never reads as the whole section.
const CHILDREN = ['All workflows', 'Deployments', 'Collections', 'Changes', 'Tool calls', 'Audit log', 'Suites', 'Model inventory'];

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const nav = page.locator('[data-sidebar="sidebar"]');
      const subRows = nav.locator('[data-sidebar="menu-sub-button"]');
      const active = async () => (await nav.locator('[data-active="true"]').allInnerTexts()).map((t) => t.trim());
      const open = async (path) => {
        await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await nav.locator('[data-sidebar="menu-button"]').first().waitFor({ timeout: 120_000 });
        await page.waitForTimeout(800);
      };

      await open('/workflows');
      const listed = (await subRows.allInnerTexts()).map((t) => t.trim());
      check('every parent lists its sub-pages as sidebar rows, open by default', JSON.stringify(listed) === JSON.stringify(CHILDREN), listed);
      check("on a one-child section's own page its own sub-row is the active one", JSON.stringify(await active()) === '["All workflows"]', await active());

      await subRows.filter({ hasText: 'Deployments' }).click();
      await page.waitForURL((u) => u.pathname === '/deployments', { timeout: 60_000 });
      await page.waitForTimeout(800);
      check('a sub-row opens its page and is the only active row', JSON.stringify(await active()) === '["Deployments"]', await active());

      await nav.getByRole('button', { name: 'Hide Wiki pages' }).click();
      await page.waitForTimeout(400);
      const hidden = !(await nav.getByText('Collections').isVisible());
      await open('/deployments');
      const stillHidden = !(await nav.getByText('Collections').isVisible());
      check("a parent the viewer closes stays closed after a reload", hidden && stillHidden, { hidden, stillHidden });

      await open('/knowledge/changes');
      check(
        "a closed parent opens when one of its pages is the current page, with that row active",
        (await nav.getByText('Changes', { exact: true }).isVisible()) && JSON.stringify(await active()) === '["Changes"]',
        await active(),
      );

      await open('/deployments');
      const switched = await (async () => {
        await page.getByTestId('title-switcher').click();
        const items = (await page.getByRole('menuitem').allInnerTexts()).map((t) => t.trim());
        await page.getByRole('menuitem', { name: 'All workflows' }).click();
        await page.waitForURL((u) => u.pathname === '/workflows', { timeout: 30_000 });
        return items;
      })().catch((e) => String(e));
      check(
        'the page-title switcher still lists the section and moves between its pages',
        JSON.stringify(switched) === '["All workflows","Deployments"]',
        switched,
      );

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
