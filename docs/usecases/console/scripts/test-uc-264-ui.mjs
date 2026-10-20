// uc-264 every page draws the shared header, ui layer: docs/usecases/console/every-page-has-the-header.md. The demo stack
// with platform sign-in as Priya (admin of Operations). Each sidebar route is opened, then the first record its list
// links to, and the page must render PageLayout's or RecordLayout's header (data-testid="page-header"). This is the
// runtime half of check-standards rule 12: the static rule can be satisfied by a branch that never renders.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PRIYA = 'p.shah@northfieldbank.com';
// Full-height shells keep their own frame (check-standards rule 12 lists them): the chat workspace and the workflow
// editor (a workflow's own page).
const SHELLS = new Set(['/chat']);
const isShell = (path) => SHELLS.has(path) || /^\/workflows\/(?!runs(\/|$))[^/]+$/.test(path);

await withUiStack(
  async (consoleUrl) => {
    // A case to open: the demo seed holds none of its own.
    const token = (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: PRIYA, password: 'northfield-demo' }) })).json()).data.token;
    const opened = await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/cases`, { method: 'POST', headers: { Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ subject: 'Card charge not recognised', customer_name: 'Alex Martin' }) });
    if (opened.status >= 300) throw new Error(`setup: opening a case answered ${opened.status}`);
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(PRIYA);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // The routes come from the sidebar the person sees, so a page added to the nav is checked without editing this.
      await page.goto(`${consoleUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('page-header').first().waitFor({ timeout: 60_000 });
      const routes = [...new Set(await page.locator('[data-sidebar="sidebar"] a[href^="/"]').evaluateAll((as) => as.map((a) => new URL(a.href).pathname)))];

      const header = async (path) => {
        await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        return page.getByTestId('page-header').first().waitFor({ timeout: 45_000 }).then(() => true, () => false);
      };
      const missing = [];
      const records = [];
      for (const route of routes) {
        if (isShell(route)) continue;
        if (!(await header(route))) {
          missing.push(route);
          continue;
        }
        // The first record this list links to, when it has one: a row's own page under the same route.
        await page.waitForTimeout(1200);
        const href = await page
          .locator(`main a[href^="${route === '/' ? '/__none__' : route}/"]`)
          .evaluateAll((as, base) => as.map((a) => new URL(a.href).pathname).find((p) => {
            const rest = p.slice(base.length + 1);
            return rest.length > 0 && !rest.includes('/') && !['new', 'connect', 'changes', 'runs', 'collections', 'conversations'].includes(rest);
          }), route)
          .catch(() => undefined);
        if (href) records.push(href);
      }
      // Lists whose rows open on click rather than through a link: their first row's page.
      for (const list of ['/reviews', '/cases', '/workflows/runs']) {
        await page.goto(`${consoleUrl}${list}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = page.locator('tbody tr[data-testid]').first();
        if (!(await row.waitFor({ timeout: 45_000 }).then(() => true, () => false))) continue;
        await row.locator('td').nth(2).click();
        await page.waitForURL((u) => u.pathname !== list && u.pathname.startsWith(list.split('/').slice(0, 2).join('/')), { timeout: 30_000 }).catch(() => undefined);
        const path = new URL(page.url()).pathname;
        if (path !== list) records.push(path);
      }
      for (const href of [...new Set(records)].filter((p) => !isShell(p))) if (!(await header(href))) missing.push(href);
      check('1 every sidebar route draws the shared header', routes.length >= 15 && !missing.some((p) => routes.includes(p)), { routes: routes.length, missing: missing.filter((p) => routes.includes(p)) });
      check('2 the first record each list opens draws the shared header', records.length >= 9 && ['/reviews/', '/cases/', '/workflows/runs/'].every((k) => records.some((p) => p.startsWith(k))) && !missing.some((p) => records.includes(p)), { records, missing: missing.filter((p) => records.includes(p)) });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true },
);
finish();
