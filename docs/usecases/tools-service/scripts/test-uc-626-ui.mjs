// uc-626 Apps screens offer only what you may do, in plain words, ui layer: docs/usecases/tools-service/
// apps-screens-for-each-role.md. A viewer and an admin walk the Apps screens of a stack with two test plugins (a
// desk signed in with a key, and one that brings resources): what each is offered, the words on every tab, the one
// state an app's Settings show, and the Connected view's empty state. No outside system is reached.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('626', 'uc');
const KEYED = 'plugin:test.header-key';
const PLUGINS = [join(ROOT, 'services/tools-service/tests/plugin_kinds/kinds_header_key'), join(ROOT, 'services/tools-service/tests/plugin_templates/templates_desk')];
// Words a person should never read on these screens: the service's nouns, the grid's cell names and team ids.
const INTERNAL = /\b(plugins?|gateway|modules?|binding|egress|oauth|team_ops|team_security)\b|connections\.\w+|\ba agent\b|Steps: draft/i;

const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });

async function signedIn(browser, consoleUrl, email) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

async function step(name, body, page) {
  try {
    await body();
  } catch (e) {
    await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
    check(name, false, `${String(e).slice(0, 300)} at ${page?.url() ?? 'no page'}`);
  }
}

const text = async (page) => ((await page.locator('main').innerText({ timeout: 30_000 }).catch(() => '')) ?? '').replace(/\s+/g, ' ');

/** Every word a person reads on the Apps screens: the catalog, an app's every tab, Auth configs, My accounts, Tools. */
async function wordsOn(page, consoleUrl, apps) {
  const seen = {};
  const read = async (where) => {
    await page.waitForTimeout(1200);
    const found = (await text(page)).match(new RegExp(INTERNAL, 'gi'));
    if (found) seen[where] = [...new Set(found)];
  };
  for (const path of ['/integrations', '/integrations/credentials', '/integrations/credentials?tab=secrets', '/integrations/my-accounts', '/tools']) {
    await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await read(path);
  }
  for (const app of apps) {
    await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(app)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    for (const tab of ['auth', 'tools', 'resources', 'logs', 'settings']) {
      await page.getByTestId(`app-tab-${tab}`).click({ timeout: 60_000 }).catch(() => undefined);
      await read(`${app} ${tab}`);
    }
  }
  await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('tools-tab-logs').click({ timeout: 60_000 }).catch(() => undefined);
  await read('/tools logs');
  return seen;
}

try {
  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const priya = as(await tokenFor('p.shah@harborpine.example'));
      let cards = [];
      for (let i = 0; i < 40 && cards.length < 2; i++) {
        cards = ((await (await fetch(`${tools}/v1/apps`, { headers: priya })).json()).data ?? []).filter((c) => c.kind === 'plugin');
        if (cards.length < 2) await new Promise((r) => setTimeout(r, 500));
      }
      const resourcesApp = cards.find((c) => c.id !== KEYED)?.id;
      check('0 set-up: both test apps are listed', Boolean(resourcesApp) && cards.some((c) => c.id === KEYED), cards.map((c) => c.id));

      const browser = await chromium.launch();
      try {
        const admin = await signedIn(browser, consoleUrl, 'p.shah@harborpine.example');
        await step('7 with no app connected, the Connected view says so and how to connect one, not that nothing matches', async () => {
          await admin.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await admin.getByRole('tab', { name: 'Connected' }).click({ timeout: 60_000 });
          await admin.waitForTimeout(800);
          const said = await text(admin);
          check('7 with no app connected, the Connected view says so and how to connect one, not that nothing matches', /No app is connected yet/.test(said) && !/No apps match/.test(said), said.slice(0, 300));
        }, admin);

        // The keyed desk turned on with a key and never tested, so its account and its Settings must agree.
        const on = await fetch(`${tools}/v1/apps/${encodeURIComponent(KEYED)}/team`, { method: 'PUT', headers: priya, body: JSON.stringify({ enabled: true, credentials: { key: 'desk-key-5b1e9c0d7a' } }) });
        check('0b set-up: the keyed desk is on for the team', on.ok, await on.text().then((t) => t.slice(0, 200)));

        const viewer = await signedIn(browser, consoleUrl, 'r.menon@harborpine.example');
        await step('2 a viewer is offered no Add custom app', async () => {
          await viewer.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await viewer.getByTestId('systems-grid').waitFor({ timeout: 60_000 });
          const offered = await viewer.getByTestId('connect-system').count();
          check('2 a viewer is offered no Add custom app', offered === 0, { offered });
          // The sidebar offers no page whose API refuses the viewer: Auth configs needs managing the team's apps.
          const sidebar = viewer.locator('[data-sidebar="sidebar"]').first();
          await sidebar.getByRole('link', { name: 'Apps', exact: true }).waitFor({ timeout: 30_000 });
          const row = await sidebar.getByRole('link', { name: 'Auth configs', exact: true }).count();
          const adminRow = await admin.locator('[data-sidebar="sidebar"]').first().getByRole('link', { name: 'Auth configs', exact: true }).count();
          check('2b the sidebar offers Auth configs to an admin and not to a viewer', row === 0 && adminRow === 1, { row, adminRow });
        }, viewer);
        await step('3 a viewer opening Auth configs reads who may see them, by name, not an error', async () => {
          await viewer.goto(`${consoleUrl}/integrations/credentials`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          // The names arrive after the sentence (the team's admins are read on their own), so wait for them.
          await viewer.getByTestId('auth-configs-why').filter({ hasText: 'Priya Shah' }).waitFor({ timeout: 30_000 }).catch(() => {});
          const why = ((await viewer.getByTestId('auth-configs-why').innerText({ timeout: 30_000 }).catch(() => '')) ?? '').replace(/\s+/g, ' ');
          const failed = await viewer.getByRole('button', { name: /Try again|Retrying/ }).count();
          await viewer.screenshot({ path: join(SHOTS, 'viewer-auth-configs.png') });
          check('3 a viewer opening Auth configs reads who may see them, by name, not an error', /Ask an admin/.test(why) && /Priya Shah/.test(why) && failed === 0, { why, failed });
        }, viewer);
        await step('4 a viewer on an app’s Resources is told who adds them, with no Add selected', async () => {
          await viewer.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(resourcesApp)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await viewer.getByTestId('app-tab-resources').click({ timeout: 60_000 });
          const why = ((await viewer.getByTestId('resources-why').innerText({ timeout: 30_000 }).catch(() => '')) ?? '').replace(/\s+/g, ' ');
          const add = await viewer.getByTestId('resources-add-selected').count();
          check('4 a viewer on an app’s Resources is told who adds them, with no Add selected', add === 0 && /Builder|Admin|ask/i.test(why), { why, add });
        }, viewer);
        await step('5 neither an admin nor a viewer reads an internal word on any Apps screen', async () => {
          const apps = [KEYED, resourcesApp];
          const seen = { admin: await wordsOn(admin, consoleUrl, apps), viewer: await wordsOn(viewer, consoleUrl, apps) };
          check('5 neither an admin nor a viewer reads an internal word on any Apps screen', Object.keys(seen.admin).length === 0 && Object.keys(seen.viewer).length === 0, seen);
        }, admin);
        await step('6 an app’s Settings show the default account’s one state, the same as its Auth configs row', async () => {
          await admin.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(KEYED)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const row = await admin.locator('[data-testid^="account-state-"]').first().getAttribute('data-state', { timeout: 60_000 });
          await admin.getByTestId('app-tab-settings').click();
          const keys = await admin.getByTestId('app-keys-state').getAttribute('data-state', { timeout: 30_000 }).catch(() => null);
          const said = ((await admin.getByTestId('app-keys').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ');
          check('6 an app’s Settings show the default account’s one state, the same as its Auth configs row', Boolean(row) && keys === row && !/Working|Not tested|Failing/.test(said), { row, keys, said });
        }, admin);
        await step('8 a custom app’s Run test that misses a field shows that field, opened, with the reason', async () => {
          await admin.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await admin.getByTestId('connect-system').click({ timeout: 60_000 });
          await admin.locator('#system-name').fill('Harbor desk');
          await admin.locator('#account-baseUrl').fill('https://desk.example/v1');
          await admin.locator('#account-key').fill('desk-key-1234');
          await admin.getByTestId('account-test').click({ timeout: 30_000 });
          const field = admin.locator('#account-testPath');
          const shown = await field.waitFor({ state: 'visible', timeout: 30_000 }).then(() => true, () => false);
          const said = ((await admin.getByTestId('account-fields').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ');
          await admin.screenshot({ path: join(SHOTS, 'custom-app-missing-field.png') });
          await admin.keyboard.press('Escape');
          check('8 a custom app’s Run test that misses a field shows that field, opened, with the reason', shown && /test address/i.test(said), { shown, said: said.slice(0, 300) });
        }, admin);
        check('9 no page errors', admin.errors.length === 0 && viewer.errors.length === 0, [...admin.errors, ...viewer.errors].slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    { platform: true, tools: { env: { OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify(PLUGINS) } } },
  );
} finally {
  finish();
}
