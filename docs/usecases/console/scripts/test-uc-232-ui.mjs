// uc-232 The workspace name and the tool list come from the services, ui layer: docs/usecases/console/shell-real-data.md.
// Platform sign-in; James works in Operations.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
    const me = (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/me`, { headers: J })).json()).data;
    const wfTools = (await (await fetch(`${agents}/v1/tools?kind=workflow&pageSize=200`, { headers: J })).json()).data.data;
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // The sidebar's team switcher reads "<team>" over "<workspace> · Ops AI"; the header no longer repeats either.
      const workspace = page.getByTestId('sidebar-workspace');
      // The subtitle reads "Ops AI" alone until /v1/me answers; wait for the workspace part before comparing.
      await workspace.filter({ hasText: ' · ' }).waitFor({ timeout: 30_000 }).catch(() => {});
      const said = (await workspace.innerText()).trim();
      const team = (await page.getByTestId('sidebar-team').innerText()).trim();
      check('1 the sidebar names the workspace as platform-service does, under the team, with no sample environment', !!me?.tenantName && said === `${me.tenantName} · Ops AI` && team === 'Operations', { said, team, tenantName: me?.tenantName });
      const headerText = await page.locator('header').first().innerText();
      check('1b the header does not repeat the workspace or the team', !headerText.includes(me.tenantName) && !headerText.includes('Operations'), { headerText });

      await page.goto(`${consoleUrl}/tools/custom`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const tab = page.getByRole('tab', { name: /^Workflows/ }).or(page.getByRole('button', { name: /^Workflows ·/ })).first();
      await tab.waitFor({ timeout: 60_000 });
      // The count reads 0 until the directory answers.
      await tab.filter({ hasText: `· ${wfTools.length}` }).waitFor({ timeout: 30_000 }).catch(() => {});
      const label = (await tab.innerText()).trim();
      check('2 Tools › Workflows counts the directory’s workflow tools', label.includes(`· ${wfTools.length}`), { label, directory: wfTools.length });
      // The workspace admin names the workspace over the platform API; a builder is refused, and the sidebar shows it.
      const rename = async (email, team, name) =>
        fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/settings/workspace`, {
          method: 'PATCH',
          headers: { Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': team, 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
      const refused = (await rename(JAMES, 'team_ops', 'Not Allowed')).status;
      const renamed = await rename('w.kamau@harborpine.example', 'team_platform', 'Harbor & Pine Bank');
      await page.reload({ waitUntil: 'domcontentloaded' });
      const after = page.getByTestId('sidebar-workspace');
      const shows = await after.filter({ hasText: 'Harbor & Pine Bank' }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('3 the workspace admin names the workspace through the platform API, a builder is refused, and the sidebar shows the new name', renamed.status === 200 && refused === 403 && shows, { renamed: renamed.status, refused, shows });

      // 4 On Settings › Workspace the builder sees the name locked; Wanjiru renames it there and the sidebar follows.
      await page.goto(`${consoleUrl}/settings/workspace`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const builderLocked = await page.getByTestId('workspace-name').isDisabled({ timeout: 30_000 });
      const admin = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
      admin.on('pageerror', (e) => errors.push(e.message));
      await admin.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await admin.getByLabel('Email').fill('w.kamau@harborpine.example');
      await admin.getByLabel('Password').fill('northfield-demo');
      await admin.getByRole('button', { name: /^Sign in/ }).first().click();
      await admin.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await admin.goto(`${consoleUrl}/settings/workspace`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const field = admin.getByTestId('workspace-name');
      await field.waitFor({ timeout: 30_000 });
      for (let i = 0; i < 30 && (await field.isDisabled()); i++) await admin.waitForTimeout(500);
      await field.fill('Harbor & Pine Bank Operations');
      const saved = admin.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith('/v1/settings/workspace'), { timeout: 30_000 }).catch(() => null);
      await admin.locator('#name').getByRole('button', { name: 'Save' }).click();
      const answer = await saved;
      // Settings has its own sidebar; the team switcher is on every work page.
      await admin.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const sidebarShows = await admin.getByTestId('sidebar-workspace').filter({ hasText: 'Harbor & Pine Bank Operations' }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('4 Settings › Workspace saves the name for a workspace admin, and is locked for a builder', builderLocked && answer?.status() === 200 && sidebarShows, { builderLocked, status: answer?.status(), sidebarShows });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);
finish();
