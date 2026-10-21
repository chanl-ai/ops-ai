// uc-127 the live console follows the owner's layout rules, ui layer: docs/usecases/console/layout-rules-sweep.md.
// Signed in through platform-service as James (builder). One check per rule, on the pages that have the control.
import { PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const TAG = Math.random().toString(36).slice(2, 6);
const JAMES = 'j.richardson@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const signIn = async (browser, consoleUrl, width = 1440, email = JAMES) => {
  const page = await (await browser.newContext({ viewport: { width, height: 1000 } })).newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};
const openWidget = async (page, consoleUrl) => {
  await page.goto(`${consoleUrl}/widgets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('new-widget-button').click({ timeout: 120_000 });
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name').fill(`Layout ${TAG}`);
  await dialog.getByLabel('When the agent uses it').fill('The person asks for a layout check.');
  await dialog.getByLabel('Name').press('Enter');
  await page.waitForURL((u) => /^\/widgets\/[^/]+$/.test(u.pathname), { timeout: 30_000 });
  await page.getByTestId('widget-preview').waitFor({ timeout: 60_000 });
};
// Luminance of any CSS colour, through a canvas pixel, so oklch and color-mix values compare alike.
const lum = (page, selector) =>
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
    return { field: px(getComputedStyle(document.querySelector(sel)).backgroundColor), page: px(getComputedStyle(document.body).backgroundColor) };
  }, selector);

await withUiStack(
  async (consoleUrl) => {
    const S = { Authorization: `Bearer ${await tokenFor(SAM)}`, 'X-Team-Id': 'team_security', 'Content-Type': 'application/json' };
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: `layout-${TAG}.bank.example`, note: 'uc-127' }) });
    await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: S, body: JSON.stringify({ name: `LAYOUT_${TAG.toUpperCase()}`, value: 'not-a-key' }) });
    const browser = await chromium.launch();
    try {
      const page = await signIn(browser, consoleUrl);
      await openWidget(page, consoleUrl);

      // Rule 1: input, textarea and select are lighter than the page, in light and dark.
      const fields = ['#widget-name', '#widget-use-when'];
      const measure = async () => Object.fromEntries(await Promise.all(fields.map(async (f) => [f, await lum(page, f)])));
      const light = await measure();
      await page.evaluate(() => document.documentElement.classList.add('dark'));
      const dark = await measure();
      await page.evaluate(() => document.documentElement.classList.remove('dark'));
      const lighter = (m) => Object.values(m).every((x) => x.field > x.page);
      // A picker trigger (the rows-per-page select on Workflows) and the tag input on the widget-free Guardrails dialog.
      await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('combobox').first().waitFor({ timeout: 120_000 });
      const picker = await lum(page, '[role="combobox"]');
      await page.evaluate(() => document.documentElement.classList.add('dark'));
      const pickerDark = await lum(page, '[role="combobox"]');
      await page.evaluate(() => document.documentElement.classList.remove('dark'));
      await page.goto(`${consoleUrl}/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('new-guardrail-button').click({ timeout: 120_000 });
      await page.getByRole('dialog').getByLabel('Blocked topics').waitFor({ timeout: 30_000 });
      const tagBox = await page.evaluate(() => {
        const wrap = document.querySelector('[role="dialog"] input[aria-label="Blocked topics"], [role="dialog"] #topics')?.closest('div[class*="border-input"]') ?? [...document.querySelectorAll('[role="dialog"] div')].find((d) => /border-input/.test(d.className) && d.querySelector('input'));
        const px = (css) => { const c = document.createElement('canvas'); c.width = c.height = 1; const g = c.getContext('2d'); g.fillStyle = css; g.fillRect(0, 0, 1, 1); const [r, gg, b] = g.getImageData(0, 0, 1, 1).data; return 0.2126 * r + 0.7152 * gg + 0.0722 * b; };
        return wrap ? { field: px(getComputedStyle(wrap).backgroundColor), page: px(getComputedStyle(document.body).backgroundColor) } : null;
      });
      await page.keyboard.press('Escape');
      check('rule 1: fields on the widget page are lighter than the page, in light and dark', lighter(light) && lighter(dark), { light, dark });
      check('rule 1: a picker trigger (light and dark) and the tag input are lighter than the page too', picker.field > picker.page && pickerDark.field > pickerDark.page && !!tagBox && tagBox.field > tagBox.page, { picker, pickerDark, tagBox });

      await page.goto(`${consoleUrl}/widgets/layout-${TAG}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('widget-preview').waitFor({ timeout: 60_000 });
      // Rule 2: the widget definition and its preview are a split with a drag handle that is remembered; below lg they stack.
      const handle = page.locator('[data-slot="resizable-handle"]').first();
      await handle.waitFor({ timeout: 30_000 });
      const left = () => page.locator('[data-slot="resizable-panel"]').first().evaluate((e) => Math.round(e.getBoundingClientRect().width));
      const w0 = await left();
      const box = await handle.boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + 40);
      await page.mouse.down();
      await page.mouse.move(box.x + 160, box.y + 40, { steps: 8 });
      await page.mouse.up();
      const w1 = await left();
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.locator('[data-slot="resizable-handle"]').first().waitFor({ timeout: 60_000 });
      const w2 = await left();
      await page.setViewportSize({ width: 800, height: 1000 });
      await page.waitForTimeout(500);
      const stacked = (await page.locator('[data-slot="resizable-handle"]').count()) === 0 && (await page.getByTestId('widget-preview').isVisible());
      check('rule 2: the widget page splits with a drag handle, keeps the split after a reload, and stacks below lg', w1 > w0 + 60 && Math.abs(w2 - w1) <= 6 && stacked, { w0, w1, w2, stacked });

      // Rule 2, the other splits: agent Settings and a record page's rail (model inventory) carry a drag handle. The knowledge
      // Retrieval tab and the tool workbench are converted but not reached here: the first is mounted nowhere, the second needs a module.
      await page.setViewportSize({ width: 1440, height: 1000 });
      const firstLink = async (path, prefix) => {
        await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const a = page.locator(`tbody a[href^="${prefix}"]`).first();
        await a.waitFor({ timeout: 120_000 });
        return a.getAttribute('href');
      };
      const handles = {};
      for (const [path, prefix, suffix] of [['/agents', '/agents/', ''], ['/model-risk', '/model-risk/', '']]) {
        const href = await firstLink(path, prefix);
        await page.goto(`${consoleUrl}${href}${suffix}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        handles[path] = await page.locator('[data-slot="resizable-handle"]').first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      }
      check('rule 2: agent settings and a record page rail each have a drag handle', Object.values(handles).every(Boolean), handles);

      // Rule 3: at 320px the tab labels of a record page sit inside their tabs and the page does not widen.
      const narrow = await signIn(browser, consoleUrl, 320);
      await narrow.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const link = narrow.locator('tbody a[href^="/workflows/"]').first();
      await link.waitFor({ timeout: 120_000 });
      await narrow.goto(`${consoleUrl}${await link.getAttribute('href')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await narrow.locator('[data-slot="tabs-list"]').first().waitFor({ timeout: 60_000 });
      const tabs = await narrow.evaluate(() => {
        const list = document.querySelector('[data-slot="tabs-list"]');
        const triggers = [...list.querySelectorAll('[data-slot="tabs-trigger"]')];
        return { count: triggers.length, spilled: triggers.filter((t) => t.scrollWidth > t.clientWidth + 1).length, page: document.documentElement.scrollWidth <= window.innerWidth + 1, scrolls: list.scrollWidth > list.clientWidth, overflowX: getComputedStyle(list).overflowX };
      });
      check('rule 3: at 320px no tab label spills its tab, the list scrolls sideways and the page does not widen', tabs.count >= 4 && tabs.spilled === 0 && tabs.page && tabs.scrolls && tabs.overflowX === 'auto', tabs);

      // Rule 4: every table of records starts with select-all and shows a middle-truncated, copyable id. Secrets and Egress
      // list a key (the name or host is the id), so they have select-all and no separate Id column.
      const sam = await signIn(browser, consoleUrl, 1440, SAM);
      const withId = ['/agents', '/workflows', '/integrations', '/model-risk', '/guardrails', '/widgets', '/knowledge', '/logs/tool-calls', '/logs/audit', '/settings/webhooks', '/settings/api-keys', '/cases', '/reviews'];
      const keyed = ['/settings/secrets', '/settings/egress'];
      const asSam = [...keyed, '/logs/audit'];
      const nested = [];
      for (const w of [page, sam]) w.on('console', (m) => m.type() === 'error' && /descendant|cannot contain a nested/.test(m.text()) && nested.push(m.text().slice(0, 80)));
      const lists = {};
      for (const path of [...withId, ...keyed]) {
        const who = asSam.includes(path) ? sam : page;
        await who.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await who.locator('tbody tr').first().waitFor({ timeout: 120_000 }).catch(() => undefined);
        lists[path] = await who.evaluate(() => {
          const heads = [...document.querySelectorAll('thead th')].map((th) => th.textContent?.trim() ?? '');
          const first = document.querySelector('tbody tr');
          return {
            selectAll: !!document.querySelector('thead [role="checkbox"][aria-label="Select all on this page"]'),
            idHead: heads.includes('Id'),
            copy: !!first?.querySelector('button[aria-label^="Copy id"]'),
            rows: document.querySelectorAll('tbody tr').length,
          };
        });
      }
      // A list the stack has no records for still draws its header; the copy button needs a row to be found in.
      const ok = (path) => lists[path].selectAll && (keyed.includes(path) ? lists[path].rows > 0 && !lists[path].idHead : lists[path].idHead && (lists[path].rows === 0 || lists[path].copy));
      check('rule 4: a copyable id inside an opening row nests no button in a button', nested.length === 0, nested);
      check('rule 4: every list of records starts with select-all, and all but the keyed ones (secrets, egress) have an Id column with a copy button', Object.keys(lists).every(ok), Object.fromEntries(Object.entries(lists).filter(([k]) => !ok(k))));

      // Rule 5: a record page's primary actions sit in the header's actions slot, not in a row above its table.
      const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const made = await (await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Layout ${TAG}`, name: `layout-${TAG}`, type: 'http' }) })).json();
      await fetch(`${tools}/v1/tool-modules/${made.data.id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: `get_layout_${TAG}`, description: '', access: 'read', method: 'GET', url: `https://layout-${TAG}.bank.example/v1/x` }) });
      await page.goto(`${consoleUrl}/tools/${made.data.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('ops-add').first().waitFor({ timeout: 120_000 });
      const actions = {
        inHeader: await page.getByTestId('page-header').getByTestId('ops-add').count(),
        inBody: await page.locator('main, [data-testid="page-header"] ~ *').getByTestId('ops-add').count(),
        total: await page.getByTestId('ops-add').count(),
      };
      check('rule 5: Add operation and Import are in the tool page header, once', actions.inHeader === 1 && actions.total === 1, actions);

      const errors = [...(page.errors ?? []), ...(narrow.errors ?? []), ...(sam.errors ?? [])];
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
