// uc-780 A long list or text in a table cell stays inside its column, ui layer:
// docs/usecases/console/long-values-in-tables.md. Demo stack, signed in as James (builder).
import { check, chromium, consoleSignIn, expectSampleData, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD } from '@ops-ai/usecase-runner/steps';

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}
const overflows = (page) => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
const tableScrolls = (page) => page.evaluate(() => [...document.querySelectorAll('[data-slot=table-container]')].some((t) => t.scrollWidth > t.clientWidth + 1));

// The model risk pages and some list pages are still answered by the console's mock.
expectSampleData('/govern/models', '/build/guardrails', '/data/wiki', '/data/tools', '/data/knowledge', '/build/agents');

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, 'j.richardson@harborpine.example', PASSWORD, errors);
      page.setDefaultTimeout(30_000);
      const open = async (path) => {
        await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.waitForLoadState('networkidle').catch(() => {});
      };

      await step('1 a long list shows three values and +N more with every value in the popover', async () => {
        await open('/data/document-types/legal_notice');
        const more = page.getByRole('button', { name: /^\+\d+ more$/ }).first();
        await more.waitFor();
        const n = Number((await more.innerText()).match(/\d+/)[0]);
        await more.click();
        const pop = page.getByRole('dialog', { name: 'Allowed values' }).or(page.locator('[data-slot=popover-content]')).first();
        const items = await pop.locator('li').count();
        check('1 the popover holds every value', items === n + 3, { items, n });
        await page.keyboard.press('Escape');
        const wide = [];
        for (const w of [1440, 390]) {
          await page.setViewportSize({ width: w, height: 900 });
          wide.push([w, await overflows(page), w >= 1024 && (await tableScrolls(page))]);
        }
        check('1 the table does not scroll sideways at 1440 and the page not at 390', !wide[0][1] && !wide[0][2] && !wide[1][1], wide);
        await page.setViewportSize({ width: 1440, height: 900 });
      });

      await step('2 +N more inside a clickable row does not open the row', async () => {
        let proved = null;
        for (const path of ['/govern/access/tool-access', '/build/guardrails', '/govern/access', '/data/wiki/collections', '/data/tools/custom', '/data/knowledge']) {
          await open(path);
          const more = page.locator('tbody tr').getByRole('button', { name: /^\+\d+ more$/ }).first();
          if (!(await more.count())) continue;
          const before = page.url();
          await more.click();
          const pop = page.locator('[data-slot=popover-content]').first();
          await pop.waitFor();
          await pop.locator('li').first().click();
          await page.waitForTimeout(500);
          proved = { path, stayed: page.url() === before, url: page.url() };
          break;
        }
        check('2 the address stays and the popover opens on a clickable row', !!proved && proved.stayed, proved ?? 'no row with +N more on the list pages tried');
        console.log('step 2 proved on', JSON.stringify(proved));
      });

      await step('3 a cut text opens whole in a popover', async () => {
        await open('/govern/models/mr_wf_wire');
        const cut = page.locator('[data-testid=model-findings] button[title]').first();
        await cut.waitFor();
        const full = await cut.getAttribute('title');
        await cut.focus();
        await page.keyboard.press('Enter');
        const pop = page.locator('[data-slot=popover-content]').first();
        await pop.waitFor();
        check('3 the popover holds the whole text', (await pop.innerText()).trim() === full && (await pop.getAttribute('aria-label')) === 'Full text', { full });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
