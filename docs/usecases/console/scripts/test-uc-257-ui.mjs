// uc-257 Tables size each column by what it holds, ui layer: docs/usecases/console/table-column-kinds.md. Platform
// sign-in as Priya; the stack's seeded workflows fill the Workflows table, the widest list in the console.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

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
      const signIn = async (width) => {
        const page = await (await browser.newContext({ viewport: { width, height: 900 } })).newPage();
        page.setDefaultTimeout(60_000);
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill('p.shah@northfieldbank.com');
        await page.getByLabel('Password').fill('northfield-demo');
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.locator('tbody tr').first().waitFor({ timeout: 60_000 });
        return page;
      };
      const page = await signIn(1280);
      // Column order on the Workflows table: select, id, Workflow (a name), then counts and stages.
      const cells = (col) => page.locator(`tbody tr td:nth-child(${col})`);

      await step('1 a name takes the free space on one line, trimmed, with the whole name on hover', async () => {
        const name = cells(3).first();
        const title = await name.getAttribute('title');
        const text = (await name.locator('div').first().innerText()).split('\n')[0];
        // Every line inside the cell is one line high: nothing wraps.
        const lines = await name.evaluate((td) => [...td.querySelectorAll('div')].filter((d) => d.children.length === 0 || d.childElementCount === 0).map((d) => Math.round(d.getBoundingClientRect().height)));
        const ellipsis = await name.evaluate((td) => [...td.querySelectorAll('div')].some((d) => getComputedStyle(d).textOverflow === 'ellipsis'));
        check('1 a name takes the free space on one line, trimmed, with the whole name on hover', !!title && title.length >= text.length && lines.every((h) => h <= 24) && ellipsis, { title, text, lines, ellipsis });
      });

      await step('2 counts are right-aligned on one line', async () => {
        const header = (await page.locator('thead th').allInnerTexts()).map((t) => t.trim());
        const col = header.findIndex((t) => /^Runs · 24h/.test(t)) + 1;
        const align = await cells(col).first().evaluate((td) => [getComputedStyle(td).textAlign, getComputedStyle(td).whiteSpace]);
        check('2 counts are right-aligned on one line', col > 0 && align[0] === 'right' && align[1] === 'nowrap', { col, align });
      });

      await step('3 a column cell that draws nothing shows a dash', async () => {
        // The rule is on every kind cell: an empty cell of the same column, as the table draws it, shows the dash.
        const dash = await cells(3).first().evaluate((td) => {
          const empty = document.createElement('td');
          empty.className = td.className;
          td.parentElement.appendChild(empty);
          const content = getComputedStyle(empty, '::after').content;
          empty.remove();
          return content;
        });
        check('3 a column cell that draws nothing shows a dash', dash === '"—"', { dash });
      });

      await step('4 at 400px the name stays pinned beside the select box while the counts scroll, and the page never scrolls sideways', async () => {
        const narrow = await signIn(400);
        const name = narrow.locator('tbody tr td:nth-child(3)').first();
        const pinned = await name.evaluate((td) => [getComputedStyle(td).position, getComputedStyle(td).left]);
        const box = narrow.locator('table').first().locator('xpath=..');
        await box.evaluate((el) => el.scrollTo(300, 0));
        const before = await name.boundingBox();
        const sideways = await narrow.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        check('4 at 400px the name stays pinned beside the select box while the counts scroll, and the page never scrolls sideways', pinned[0] === 'sticky' && pinned[1] === '40px' && sideways <= 0 && !!before, { pinned, sideways });
      });

      await step('5 a list shows six data columns, the rest under View by name, and a column turned on stays on after a reload', async () => {
        const headers = async () => (await page.locator('thead th').allInnerTexts()).map((t) => t.trim()).filter(Boolean);
        const shown = await headers();
        await page.getByRole('button', { name: 'View', exact: true }).first().click();
        const menu = page.getByRole('menu');
        const offered = (await menu.getByRole('menuitemcheckbox').allInnerTexts()).map((t) => t.trim());
        const hidden = menu.locator('[role="menuitemcheckbox"][data-state="unchecked"]').first();
        const name = (await hidden.innerText()).trim();
        await hidden.click();
        await page.keyboard.press('Escape');
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.locator('tbody tr').first().waitFor({ timeout: 60_000 });
        const after = await headers();
        check(
          '5 a list shows six data columns, the rest under View by name, and a column turned on stays on after a reload',
          shown.length <= 7 && offered.length > shown.length - 1 && offered.every((t) => !/[a-z][A-Z]/.test(t)) && !!name && !shown.includes(name) && after.some((h) => h.startsWith(name)),
          { shown, offered, name, after },
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
