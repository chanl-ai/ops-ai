// uc-152 the live settings follow the approved tree, ui layer: docs/usecases/console/settings-tree-live.md.
// Signed in through platform-service as Sam (Security admin). Settings has its own sidebar; a moved page answers at its
// new route and its old route redirects to it.
import { PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

// Old route -> new route, one entry per page moved so far.
const MOVED = [
  ['/reviews/policies', '/settings/policies/gates'],
  ['/settings/publish-reviews', '/settings/policies/publish-reviews'],
  ['/settings/general', '/settings/team'],
  ['/account/security', '/settings/account/security'],
  ['/account', '/settings/account'],
  ['/settings/usage', '/settings/workspace/usage'],
  ['/settings/secrets', '/settings/security/secrets'],
  ['/settings/egress', '/settings/security/egress'],
  ['/settings/sign-in', '/settings/security/sign-in'],
  ['/settings/notifications', '/settings/team/notifications'],
  ['/settings/webhooks', '/settings/team/webhooks'],
  ['/settings/api-keys', '/settings/team/api-keys'],
  ['/settings/storage', '/settings/workspace/storage'],
];

const signIn = async (browser, consoleUrl, email = 's.adeyemi@northfieldbank.com') => {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const sam = await signIn(browser, consoleUrl);

      // Inside settings the app sidebar is replaced by the settings sidebar: back arrow, Find, groups, My account.
      await sam.goto(`${consoleUrl}/settings/webhooks`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('page-header').waitFor({ timeout: 120_000 });
      const shell = {
        back: await sam.getByRole('link', { name: 'Back to the console' }).count(),
        find: await sam.getByTestId('settings-find').count(),
        appNav: await sam.getByRole('link', { name: 'Human Tasks', exact: true }).count(),
        groups: await sam.locator('[data-sidebar="group-label"]').allInnerTexts(),
        mine: await sam.getByRole('link', { name: 'My account', exact: true }).count(),
        roleSwitch: await sam.getByTestId('viewer-role').count(),
      };
      check('settings has its own sidebar: back arrow, Find, Workspace, Team and Govern, My account, and no role switch', shell.back === 1 && shell.find === 1 && shell.appNav === 0 && ['Workspace', 'Team', 'Govern'].every((g) => shell.groups.includes(g)) && shell.mine === 1 && shell.roleSwitch === 0, shell);

      // F focuses Find, a search names the page and opens it.
      await sam.locator('body').click({ position: { x: 700, y: 500 } });
      await sam.keyboard.press('f');
      await sam.keyboard.type('storage');
      const hit = sam.getByTestId('settings-find-results').getByRole('link', { name: /Storage/ });
      const found = await hit.waitFor({ timeout: 10_000 }).then(() => true, () => false);
      await hit.click();
      await sam.waitForURL(/\/settings\/(workspace\/)?storage/, { timeout: 30_000 });
      check('F focuses Find and a search opens the page', found);

      // The page's primary action is in the header, once, and the page header names the section.
      await sam.goto(`${consoleUrl}/settings/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('page-header').getByRole('button', { name: 'Add secret' }).waitFor({ timeout: 120_000 });
      const header = {
        title: await sam.getByTestId('page-title').first().innerText(),
        add: await sam.getByRole('button', { name: 'Add secret' }).count(),
      };
      check('Secrets names itself in the page header and its Add secret button is there once', header.title === 'Secrets' && header.add === 1, header);

      // The secret picker: a builder picks an existing secret as a header value and has no Add option; a Security admin has it.
      const tools = `http://127.0.0.1:${TOOLS_PORT}`;
      const tok = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
      const tag = Math.random().toString(36).slice(2, 6);
      const S = { Authorization: `Bearer ${await tok('s.adeyemi@northfieldbank.com')}`, 'X-Team-Id': 'team_security', 'Content-Type': 'application/json' };
      const J = { Authorization: `Bearer ${await tok('j.richardson@northfieldbank.com')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const KEY = `PICK_${tag.toUpperCase()}`;
      await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: S, body: JSON.stringify({ name: KEY, value: 'not-a-key' }) });
      await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: `pick-${tag}.bank.example`, note: 'uc-152' }) });
      const made = await (await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Pick ${tag}`, name: `pick-${tag}`, type: 'http' }) })).json();
      const opName = `get_pick_${tag}`;
      await fetch(`${tools}/v1/tool-modules/${made.data.id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: opName, description: '', access: 'read', method: 'GET', url: `https://pick-${tag}.bank.example/v1/x` }) });
      const james = await signIn(browser, consoleUrl, 'j.richardson@northfieldbank.com');
      await james.goto(`${consoleUrl}/tools/${made.data.id}/operations/${opName}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByRole('button', { name: 'Add header' }).click({ timeout: 120_000 });
      await james.getByRole('button', { name: 'Insert a secret as the header value' }).first().click();
      const addOption = await james.getByRole('option', { name: 'Add a secret' }).count();
      await james.getByRole('option', { name: KEY }).click();
      const value = await james.getByLabel('Header value').first().inputValue();
      // Whether Add a secret shows follows the server's grid for him, not a role named in the console.
      const perms = (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/me/permissions`, { headers: { Authorization: `Bearer ${await tok('j.richardson@northfieldbank.com')}` } })).json()).data;
      const mayAdd = perms.teams.some((t) => t.permissions.some((p) => p.area === 'secrets_egress' && p.action === 'create'));
      check('a builder picks a secret as a header value and is offered Add a secret exactly when the server’s grid lets him', value === `{{${KEY}}}` && (addOption === 1) === mayAdd, { value, addOption, mayAdd });
      await sam.goto(`${consoleUrl}/tools/${made.data.id}/operations/${opName}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByRole('button', { name: 'Add header' }).click({ timeout: 120_000 }).catch(() => undefined);
      await sam.getByRole('button', { name: 'Insert a secret as the header value' }).first().click({ timeout: 10_000 }).catch(() => undefined);
      const samAdd = await sam.getByRole('option', { name: 'Add a secret' }).count();
      check('a Security admin is offered Add a secret in the same picker', samAdd === 1, { samAdd });

      // Workspace General and Team General are sample data and say so; Team General also holds the live default agent.
      const general = {};
      for (const path of ['/settings/workspace', '/settings/team']) {
        await sam.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await sam.getByTestId('page-header').waitFor({ timeout: 120_000 });
        await sam.getByTestId('sample-data-notice').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
        general[path] = {
          notice: await sam.getByTestId('sample-data-notice').count(),
          saveEnabled: await sam.locator('[data-testid="sample-data-gate"] button[type="submit"]:enabled').count(),
          defaultAgent: await sam.getByText('Default agent', { exact: true }).count(),
        };
      }
      check('Workspace General and Team General say they are sample data with Save off; Team General also holds the default agent', general['/settings/workspace'].notice === 1 && general['/settings/team'].notice === 1 && general['/settings/workspace'].saveEnabled === 0 && general['/settings/team'].saveEnabled === 0 && general['/settings/team'].defaultAgent === 1, general);

      // One sidebar row is current: Webhooks under /settings/team/webhooks, not General.
      await sam.goto(`${consoleUrl}/settings/team/webhooks`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('page-header').waitFor({ timeout: 120_000 });
      const current = await sam.locator('[data-sidebar="menu-button"][data-active="true"], [data-sidebar="menu-sub-button"][data-active="true"]').allInnerTexts();
      check('on Team › Webhooks exactly Webhooks is the current sidebar row', current.length === 1 && current[0].trim() === 'Webhooks', current);

      // My account › Memory: a tab of the account, the memory list inside it, and no Preview badge (agents-service serves it).
      await sam.goto(`${consoleUrl}/settings/account/memory`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('account-memory').waitFor({ timeout: 120_000 });
      await sam.waitForTimeout(500);
      const memory = {
        tab: await sam.getByRole('tab', { name: 'Memory' }).or(sam.getByRole('link', { name: 'Memory', exact: true })).count(),
        body: (await sam.getByTestId('account-memory').innerText()).trim().length > 0,
        preview: await sam.getByTestId('page-header').getByTestId('preview-badge').count(),
      };
      check('My account has a Memory tab that lists what agents remember and carries no Preview badge', memory.tab > 0 && memory.body && memory.preview === 0, memory);

      // Each moved page answers at its new route and the old route redirects to it.
      const seen = {};
      for (const [from, to] of MOVED) {
        await sam.goto(`${consoleUrl}${from}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await sam.getByTestId('page-header').waitFor({ timeout: 120_000 });
        seen[from] = new URL(sam.url()).pathname === to;
      }
      // Storage is served by files-service, so it keeps no Preview badge at its new route.
      await sam.goto(`${consoleUrl}/settings/workspace/storage`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByTestId('page-header').waitFor({ timeout: 120_000 });
      await sam.waitForTimeout(500);
      check('Storage at its new route shows no Preview badge', (await sam.getByTestId('page-header').getByTestId('preview-badge').count()) === 0);
      check('every moved page lives at its new route and its old route redirects there', Object.values(seen).every(Boolean), seen);

      check('no page errors', (sam.errors ?? []).length === 0, sam.errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
