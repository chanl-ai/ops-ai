// uc-769 My apps is a page of its own, the same for an admin and a member, ui layer:
// docs/usecases/console/my-apps-page.md. Demo stack signed in through platform-service as Priya (admin) and James
// (builder): the old address lands on /work/apps, no switch, a card opens its own page, Connect for the person's own
// sign-in, and nothing overflows at 390.
import { check, chromium, consoleSignIn, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD } from '@ops-ai/usecase-runner/steps';

const PEOPLE = [
  ['Priya', 'p.shah@harborpine.example', true],
  ['James', 'j.richardson@harborpine.example', false],
];

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

const overflows = (page) => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      for (const [who, email, admin] of PEOPLE) {
        const page = await consoleSignIn(browser, consoleUrl, email, PASSWORD, errors);
        page.setDefaultTimeout(30_000);
        const label = (n, t) => `${who} ${n} ${t}`;

        await step(label(1, 'the old address lands on My apps with no switch'), async () => {
          await page.goto(`${consoleUrl}/settings/account/connectors`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('connectors').or(page.getByTestId('connectors-empty')).first().waitFor({ timeout: 60_000 });
          const title = (await page.getByTestId('page-title').first().innerText()).trim();
          const body = await page.locator('main').innerText();
          check(label(1, 'the old address lands on My apps with no switch'), new URL(page.url()).pathname === '/work/apps' && title === 'My apps' && (await page.getByTestId('title-switcher').count()) === 0 && !/Team setup|connectors/i.test(body), { url: page.url(), title });
        });

        await step(label(2, 'My apps leads Work under New chat'), async () => {
          await page.setViewportSize({ width: 1440, height: 1000 });
          const hrefs = await page.locator('[data-sidebar=header] a, [data-sidebar=content] a').evaluateAll((as) => as.map((a) => new URL(a.href).pathname));
          const at = hrefs.indexOf('/work/apps');
          check(label(2, 'My apps leads Work under New chat'), at >= 0 && hrefs.slice(0, at).every((h) => h === '/chat'), hrefs.slice(0, 6));
        });

        await step(label(4, 'the person’s own sign-in is Connect, never Add an auth config'), async () => {
          const body = await page.getByTestId('connectors').innerText();
          const own = page.locator('[data-testid^="connector-action-"]');
          const words = await own.allInnerTexts();
          const askLines = await page.locator('[data-testid^="connector-ask-"]').allInnerTexts();
          const named = askLines.some((l) => l.includes(who === 'Priya' ? 'Priya Shah' : 'James Richardson'));
          check(label(4, 'the person’s own sign-in is Connect, never Add an auth config'), words.every((w) => /^(Connect|Add key|Sign in again)$/.test(w.trim())) && (admin || !named) && !(await page.locator('[data-state=needs_you] [data-testid^="connector-add-auth-config-"]').count()), { words, askLines, admin, body: body.slice(0, 200) });
        });

        await step(label(3, 'a card opens the app’s own page'), async () => {
          const first = page.locator('[data-testid^="connector-open-"]').first();
          const name = (await first.innerText()).trim();
          await first.click();
          await page.waitForURL((u) => /^\/work\/apps\/[^/]+$/.test(u.pathname), { timeout: 30_000 });
          await page.getByTestId('my-app').waitFor({ timeout: 60_000 });
          const title = (await page.getByTestId('page-title').first().innerText()).trim();
          check(label(3, 'a card opens the app’s own page'), title === name && (await page.getByTestId('connector-accounts').count()) === 1, { url: page.url(), name, title });
        });

        await step(label(6, 'nothing overflows at 390'), async () => {
          await page.setViewportSize({ width: 390, height: 844 });
          const app = await overflows(page);
          await shootBothWidths(page, 'console', `uc-769-${who.toLowerCase()}-app`, async () => page.waitForTimeout(300));
          await page.goto(`${consoleUrl}/work/apps`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('connectors').or(page.getByTestId('connectors-empty')).first().waitFor({ timeout: 60_000 });
          const list = await overflows(page);
          await shootBothWidths(page, 'console', `uc-769-${who.toLowerCase()}-list`, async () => page.waitForTimeout(300));
          check(label(6, 'nothing overflows at 390'), !app && !list, { app, list });
          await page.setViewportSize({ width: 1440, height: 1000 });
        });
      }
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
