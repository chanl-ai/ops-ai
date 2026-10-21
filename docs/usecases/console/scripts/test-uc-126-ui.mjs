// uc-126 the proposed settings tree is a mock a reviewer can walk, ui layer:
// docs/usecases/console/settings-tree-mock.md. Signed in through platform-service as Sam (Security admin). The mock
// lives under /preview/settings on sample data; nothing it does is stored.
import { PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const SAM = 's.adeyemi@harborpine.example';
const ROOT = '/preview/settings';
const PAGES = ['', '/workspace', '/workspace/storage', '/team', '/team/notifications', '/team/webhooks', '/team/api-keys', '/govern/access', '/govern/policies', '/govern/security', '/govern/models', '/account', '/agent', '/tool', '/kit'];

const signIn = async (browser, consoleUrl, email, width = 1440) => {
  const page = await (await browser.newContext({ viewport: { width, height: 1000 } })).newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && !/favicon|Failed to load resource/.test(m.text()) && page.errors.push(m.text()));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};
const go = async (page, consoleUrl, path) => {
  await page.goto(`${consoleUrl}${ROOT}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('page-title').first().waitFor({ timeout: 120_000 });
};
// Luminance of any CSS colour, through a canvas pixel, so oklch and color-mix values compare alike.
const luminance = (page, selector) =>
  page.evaluate((sel) => {
    const px = (css) => {
      const c = document.createElement('canvas');
      c.width = c.height = 1;
      const g = c.getContext('2d');
      g.fillStyle = css;
      g.fillRect(0, 0, 1, 1);
      const [r, gg, b] = g.getImageData(0, 0, 1, 1).data;
      return 0.2126 * r + 0.7152 * gg + 0.0722 * b;
    };
    const el = document.querySelector(sel);
    const bodyBg = getComputedStyle(document.body).backgroundColor;
    return { field: px(getComputedStyle(el).backgroundColor), page: px(bodyBg) };
  }, selector);

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const sam = await signIn(browser, consoleUrl, SAM);

      // Every page of the tree loads with a header and no errors.
      const loaded = {};
      for (const path of PAGES) {
        await go(sam, consoleUrl, path).then(() => (loaded[path || '/'] = true), () => (loaded[path || '/'] = false));
      }
      check('every page of the settings tree loads with a header', Object.values(loaded).every(Boolean), loaded);

      // The settings sidebar replaces the app sidebar: a way back, a Find box, the personal items at the bottom.
      await go(sam, consoleUrl, '');
      const shell = {
        back: await sam.getByRole('link', { name: 'Back to the console' }).count(),
        find: await sam.getByTestId('settings-find').count(),
        appNav: await sam.getByRole('link', { name: 'Human Tasks', exact: true }).count(),
        mine: await sam.getByRole('link', { name: 'My account', exact: true }).count(),
      };
      check('inside settings the app sidebar is replaced by a back arrow, a Find box and the personal items', shell.back === 1 && shell.find === 1 && shell.appNav === 0 && shell.mine === 1, shell);

      // F focuses Find; a search names a setting and its home; picking it opens that page.
      await sam.locator('body').click({ position: { x: 700, y: 400 } });
      await sam.keyboard.press('f');
      const focused = await sam.evaluate(() => document.activeElement?.getAttribute('data-testid'));
      await sam.keyboard.type('egress');
      const hit = sam.getByTestId('settings-find-results').getByRole('link', { name: /Egress hosts/ });
      const found = await hit.waitFor({ timeout: 10_000 }).then(() => true, () => false);
      await hit.click();
      await sam.waitForURL(/govern\/security/, { timeout: 30_000 });
      check('F focuses Find and a search lands on the setting’s page', focused === 'settings-find' && found, { focused, found });

      // One component, two shells: the tool page's dialog and Security's Egress card are the same form, and share the call.
      await sam.getByRole('link', { name: 'Tool page and dialogs' }).click();
      await sam.waitForURL(/\/tool/, { timeout: 30_000 });
      await sam.getByRole('button', { name: 'Add allowed host' }).first().click();
      const dialog = sam.getByRole('dialog', { name: 'Add allowed host' });
      await dialog.waitFor({ timeout: 10_000 });
      const preset = await dialog.getByLabel('Host').inputValue();
      await dialog.getByRole('button', { name: 'Allow host' }).click();
      await dialog.waitFor({ state: 'hidden', timeout: 10_000 });
      await sam.getByRole('button', { name: 'Add secret' }).first().click();
      const sdialog = sam.getByRole('dialog', { name: 'Add secret' });
      await sdialog.waitFor({ timeout: 10_000 });
      await sdialog.getByLabel('Value').fill('sk_test_1234abcd');
      await sdialog.getByRole('button', { name: 'Save secret' }).click();
      await sdialog.waitFor({ state: 'hidden', timeout: 10_000 });
      await sam.getByRole('link', { name: 'Security', exact: true }).click();
      await sam.waitForURL(/govern\/security/, { timeout: 30_000 });
      const inPage = {
        host: await sam.getByTestId('egress-hosts').getByText('regional.statements.harborpine.example').count(),
        secret: await sam.getByTestId('secrets-list').getByText('REGION_ROUTING_KEY').count(),
        cardAdd: await sam.getByTestId('setting-egress-add').getByRole('button', { name: 'Allow host' }).count(),
      };
      check('a host and a secret added in the tool page’s dialogs show on Security, where the same form is a card', preset === 'regional.statements.harborpine.example' && inPage.host === 1 && inPage.secret === 1 && inPage.cardAdd === 1, { preset, inPage });

      // A person without the role sees the lock with the role's name, and the card's field is off.
      await sam.getByTestId('viewer-role').click();
      await sam.getByRole('option', { name: 'Builder' }).click();
      const lock = await sam.getByTestId('setting-lock').first().innerText().catch(() => '');
      const off = await sam.getByTestId('setting-egress-add').getByLabel('Host').isDisabled();
      check('as a Builder, Security’s cards show a lock naming the Security admin and the fields are off', /Security admin/.test(lock) && off, { lock, off });
      await sam.getByTestId('viewer-role').click();
      await sam.getByRole('option', { name: 'Security admin' }).click();

      // Each setting is its own card with its own Save; the workspace page has no page-wide form.
      await go(sam, consoleUrl, '/workspace');
      const forms = await sam.locator('main form').count();
      const saves = await sam.locator('main form button[type="submit"]').count();
      const multi = await sam.locator('main form').evaluateAll((fs) => fs.filter((f) => f.querySelectorAll('button[type="submit"]').length > 1).length);
      check('Workspace › General is one form per setting, each with at most one Save, and several Saves', forms >= 8 && saves >= 5 && multi === 0, { forms, saves, multi });

      // Widths: a text field takes at least half its card, and a URL, a description or a key and value editor all of it.
      await go(sam, consoleUrl, '/workspace');
      const widths = await sam.evaluate(() => {
        const rel = (el) => {
          const content = el.closest('form').querySelector('[data-slot="card-content"]');
          const style = getComputedStyle(content);
          const inner = content.getBoundingClientRect().width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
          return Math.round((el.getBoundingClientRect().width / inner) * 100) / 100;
        };
        return { name: rel(document.querySelector('input[aria-label="Workspace name"]')), address: rel(document.querySelector('input[aria-label="Workspace address"]').closest('[data-slot="input-group"]')) };
      });
      await go(sam, consoleUrl, '/team/webhooks');
      await sam.getByRole('button', { name: 'Add webhook' }).click();
      const dialogWidths = await sam.evaluate(() => {
        const d = document.querySelector('[role="dialog"]');
        const field = (id) => Math.round(document.getElementById(id).getBoundingClientRect().width);
        return { url: field('wh-url'), name: field('wh-name'), dialog: Math.round(d.getBoundingClientRect().width) };
      });
      await sam.keyboard.press('Escape');
      check('a text field is at least half its card, an address field the whole card, and a dialog URL field the dialog body', widths.name >= 0.49 && widths.address >= 0.99 && dialogWidths.url >= dialogWidths.name && dialogWidths.url > 300, { widths, dialogWidths });

      // Policies: the seven open-by-default policies of c-186, each its own card of choices with its own Save.
      await go(sam, consoleUrl, '/govern/policies');
      const policy = {
        cards: await sam.locator('[data-testid^="setting-policy-"]').count(),
        saves: await sam.locator('[data-testid^="setting-policy-"] button[type="submit"]').count(),
        publishDefault: await sam.getByTestId('setting-policy-publish_review').getByRole('radio', { name: /^Off/ }).getAttribute('aria-checked'),
        modes: await sam.getByTestId('setting-policy-publish_review').getByRole('radio').count(),
      };
      check('Policies shows the seven policies as cards of choices, each with its own Save, publish review off by default', policy.cards === 7 && policy.saves === 7 && policy.publishDefault === 'true' && policy.modes === 3, policy);

      // Layout rules the owner checks.
      await go(sam, consoleUrl, '/workspace');
      const light = await luminance(sam, 'main input, [data-slot="input"]');
      await sam.evaluate(() => document.documentElement.classList.add('dark'));
      const dark = await luminance(sam, 'main input, [data-slot="input"]');
      await sam.evaluate(() => document.documentElement.classList.remove('dark'));
      check('fields are lighter than the page background, in light and dark', light.field > light.page && dark.field > dark.page, { light, dark });

      await go(sam, consoleUrl, '/team/api-keys');
      const table = {
        selectAll: await sam.getByRole('checkbox', { name: 'Select all on this page' }).count(),
        truncatedId: await sam.locator('tbody [data-full]').first().innerText().then((t) => t.includes('…')).catch(() => false),
        copy: await sam.locator('tbody').getByRole('button', { name: /^Copy id/ }).count(),
        action: await sam.getByTestId('page-header').getByRole('button', { name: 'Create key' }).count(),
      };
      check('a records table starts with select-all and a middle-truncated copyable id, and Create key sits in the header', table.selectAll === 1 && table.truncatedId && table.copy >= 3 && table.action === 1, table);

      const narrow = await signIn(browser, consoleUrl, SAM, 420);
      await go(narrow, consoleUrl, '/agent');
      const tabs = await narrow.evaluate(() => {
        const list = document.querySelector('[data-slot="tabs-list"]');
        const viewport = list?.closest('[data-slot="scroll-area-viewport"]');
        return { page: document.documentElement.scrollWidth <= window.innerWidth + 1, scrolls: !!viewport && viewport.scrollWidth > viewport.clientWidth };
      });
      check('eight tab labels in a 420px window scroll sideways and do not widen the page', tabs.page && tabs.scrolls, tabs);

      await go(sam, consoleUrl, '/agent');
      const handle = sam.locator('[data-slot="resizable-handle"]').first();
      await handle.waitFor({ timeout: 30_000 });
      const left = () => sam.locator('[data-slot="resizable-panel"]').first().evaluate((e) => Math.round(e.getBoundingClientRect().width));
      const w0 = await left();
      const box = await handle.boundingBox();
      await sam.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await sam.mouse.down();
      await sam.mouse.move(box.x + 140, box.y + box.height / 2, { steps: 8 });
      await sam.mouse.up();
      const w1 = await left();
      await sam.reload({ waitUntil: 'domcontentloaded' });
      await sam.locator('[data-slot="resizable-handle"]').first().waitFor({ timeout: 30_000 });
      const w2 = await left();
      check('a two-column split resizes with its handle and keeps the split after a reload', w1 > w0 + 60 && Math.abs(w2 - w1) <= 6, { w0, w1, w2 });

      const errors = [...(sam.errors ?? []), ...(narrow.errors ?? [])];
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
