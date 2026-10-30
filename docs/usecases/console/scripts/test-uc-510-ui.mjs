// uc-510 What's new, ui layer: docs/usecases/console/whats-new.md (c-510). A private stack with platform sign-in.
// 1 a fresh sign-in shows the What's new dot, and the popover lists the newest entry first with no card id or file path;
// 2 Coming next lists the roadmap; 3 after opening, a reload shows no dot; 4 with this browser's storage refusing the
// seen list, the popover still opens, the dot comes back on reload and nothing throws; 5 What's new is a round button in
// the bottom-right corner, not in the sidebar, and its popover names the version the console was built from (a release
// tag, or main and a short commit); 6 at 375 px the popover fits the screen; 8 an entry for a feature behind a release
// switch that is off (plugins, a person's own sign-in) is not listed.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const SHOTS = evidenceDir('510', 'uc');
// The console's release switches stay off for this walk, as on a release that has not turned them on.
for (const name of ['NEXT_PUBLIC_OPS_PLUGINS', 'NEXT_PUBLIC_OPS_PERSONAL_SIGNIN']) delete process.env[name];
// The newest entry as the console orders them: by date, then title; an entry behind a release switch is not shown.
const all = readdirSync(join(ROOT, 'changelog'))
  .filter((f) => f.endsWith('.json'))
  .map((f) => JSON.parse(readFileSync(join(ROOT, 'changelog', f), 'utf8')))
  .sort((a, b) => b.date.localeCompare(a.date) || a.title.localeCompare(b.title));
const entries = all.filter((e) => e.switch === undefined);
const switched = all.filter((e) => e.switch !== undefined);
const roadmap = JSON.parse(readFileSync(join(ROOT, 'roadmap.json'), 'utf8'));

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
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const trigger = page.getByTestId('whats-new-trigger');
      const popup = page.getByTestId('whats-new-popup');
      await step('1 the dot shows, and What’s new lists the newest entry first in plain words', async () => {
        await trigger.waitFor({ timeout: 60_000 });
        const dot = (await page.getByTestId('whats-new-dot').count()) === 1;
        await trigger.click();
        await popup.waitFor();
        const first = (await popup.getByTestId('whats-new-entry').first().innerText()).replace(/\s+/g, ' ');
        const text = await popup.innerText();
        await page.screenshot({ path: join(SHOTS, 'whats-new-1280.png') });
        check(
          '1 the dot shows, and What’s new lists the newest entry first in plain words',
          dot && first.includes(entries[0].title) && !/\b(?:c|uc)-\d+\b/i.test(text) && !/\b(apps|services)\/|\.(tsx?|json|py)\b/.test(text),
          { dot, first, newest: entries[0].title },
        );
        const leaked = switched.filter((e) => text.includes(e.title)).map((e) => e.title);
        check('8 an entry for a feature behind a release switch that is off is not listed', switched.length > 0 && leaked.length === 0, { switched: switched.length, leaked });
      });
      await step('2 Coming next lists the roadmap', async () => {
        await popup.getByRole('tab', { name: 'Coming next' }).click();
        const text = await page.getByTestId('coming-next').innerText();
        await page.screenshot({ path: join(SHOTS, 'coming-next-1280.png') });
        check(
          '2 Coming next lists the roadmap',
          roadmap.every((r) => text.includes(r.title)),
          { text: text.slice(0, 200) },
        );
      });
      await step('3 once opened, a reload shows no dot', async () => {
        await page.keyboard.press('Escape');
        await page.reload({ waitUntil: 'domcontentloaded' });
        await trigger.waitFor({ timeout: 60_000 });
        await page.waitForTimeout(1000);
        check('3 once opened, a reload shows no dot', (await page.getByTestId('whats-new-dot').count()) === 0);
      });
      await step('4 with storage refusing the seen list, the popover opens and the dot comes back on reload', async () => {
        const blocked = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
        await blocked.addInitScript(() => {
          const get = Storage.prototype.getItem;
          const set = Storage.prototype.setItem;
          Storage.prototype.getItem = function (k) {
            if (k === 'ops-whats-new-seen') throw new Error('storage blocked');
            return get.call(this, k);
          };
          Storage.prototype.setItem = function (k, v) {
            if (k === 'ops-whats-new-seen') throw new Error('storage blocked');
            return set.call(this, k, v);
          };
        });
        await blocked.reload({ waitUntil: 'domcontentloaded' });
        const t = blocked.getByTestId('whats-new-trigger');
        await t.waitFor({ timeout: 60_000 });
        await t.click();
        const opened = await blocked.getByTestId('whats-new-popup').isVisible();
        await blocked.keyboard.press('Escape');
        await blocked.reload({ waitUntil: 'domcontentloaded' });
        await t.waitFor({ timeout: 60_000 });
        await blocked.waitForTimeout(1000);
        const dotBack = (await blocked.getByTestId('whats-new-dot').count()) === 1;
        check('4 with storage refusing the seen list, the popover opens and the dot comes back on reload', opened && dotBack, { opened, dotBack });
      });
      await step('5 a round button in the bottom-right corner opens What’s new with the version it was built from', async () => {
        await page.setViewportSize({ width: 1280, height: 800 });
        const box = await trigger.boundingBox();
        const inSidebar = await page.locator('[data-sidebar="sidebar"] [data-testid="whats-new-trigger"]').count();
        await trigger.click();
        await popup.waitFor();
        await page.waitForTimeout(500);
        const version = (await popup.getByTestId('whats-new-version').innerText()).trim().replace(/^Version /, '');
        await page.screenshot({ path: join(SHOTS, 'whats-new-button-1280.png') });
        await page.keyboard.press('Escape');
        const corner = !!box && box.x + box.width >= 1280 - 24 && box.y + box.height >= 800 - 24 && Math.round(box.width) === 48;
        check(
          '5 a round button in the bottom-right corner opens What’s new with the version it was built from',
          corner && inSidebar === 0 && /^(v\d{4}-\d{2}-\d{2}\.\d+|main · [0-9a-f]{7,8})$/.test(version),
          { box, inSidebar, version },
        );
      });
      await step('6 at 375 px the popover opens upward and fits the screen', async () => {
        await page.setViewportSize({ width: 375, height: 760 });
        await trigger.click();
        await popup.waitFor();
        await page.waitForTimeout(500);
        const box = await popup.boundingBox();
        const sideways = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        await page.screenshot({ path: join(SHOTS, 'whats-new-375.png') });
        await page.keyboard.press('Escape');
        check('6 at 375 px the popover opens upward and fits the screen', !!box && box.x >= 0 && box.x + box.width <= 375 && box.y >= 0 && !sideways, { box, sideways });
      });
      check('7 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
