// uc-590 a team adds an app's resources as its own copies, ui layer: docs/usecases/agents-service/plugin-templates.md.
// The ui stack with plugins on and the templates desk (services/tools-service/tests/plugin_templates/
// templates_desk), turned on for Operations by Priya through the API. Priya opens the app's
// Resources tab: the agent, skill, workflow and document type each offer Add to team. Adding the agent opens its copy;
// back on the tab it reads Added and Open lands on the same copy; adding the document type opens its copy in Document
// types. Screenshots go to evidenceDir('590', 'uc').
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const PLUGIN = 'test.templates';
const APP = `plugin:${PLUGIN}`;
const FOLDER = join(ROOT, 'services/tools-service/tests/plugin_templates/templates_desk');
const SHOTS = evidenceDir('590', 'uc');

const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const call = async (base, method, path, headers, body) => {
  const r = await fetch(`${base}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  return { status: r.status, text: text.slice(0, 300) };
};

await withUiStack(
  async (consoleUrl) => {
    const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
    const team = await call(tools, 'PUT', `/v1/apps/${encodeURIComponent(APP)}/team`, priya, { enabled: true });
    check('0 set-up: the templates desk is on for Operations', team.status === 200, { team: team.text });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Work email').fill('p.shah@harborpine.example');
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByTestId('login-submit').click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const resources = async () => {
        await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('app-tab-resources').click({ timeout: 120_000 });
        await page.getByTestId('app-skills').waitFor({ timeout: 60_000 });
      };

      await resources();
      const offered = ((await page.getByTestId('app-skills').innerText()) ?? '').replace(/\s+/g, ' ');
      const adds = await page.locator('[data-testid^="resource-add-"]').count();
      await page.screenshot({ path: join(SHOTS, 'resources-1280-light.png') });
      check('1 Resources lists the agent, skill, workflow and document type, each offering Add to team', adds === 4 && /agent/.test(offered) && /skill/.test(offered) && /workflow/.test(offered) && /document type/.test(offered), { adds, offered: offered.slice(0, 300) });

      const made = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().includes('/copies'), { timeout: 60_000 });
      await page.getByTestId('resource-add-case-helper').click();
      const res = await made;
      await page.waitForURL((u) => /^\/agents\/[^/]+$/.test(u.pathname), { timeout: 60_000 }).catch(async (e) => {
        console.log('copy answered', res.status(), (await res.text().catch(() => '')).slice(0, 300), 'at', page.url());
        throw e;
      });
      const copy = new URL(page.url()).pathname;
      await resources();
      const open = page.getByTestId('resource-open-case-helper');
      const added = await open.isVisible();
      await open.click();
      await page.waitForURL((u) => u.pathname === copy, { timeout: 60_000 }).catch(() => undefined);
      const again = new URL(page.url()).pathname;
      check('2 Add to team makes the agent the team’s own copy and opens it; the tab then reads Added and Open lands on that copy', added && again === copy, { copy, again, added });

      await resources();
      await page.getByTestId('resource-add-case-letter').click();
      await page.waitForURL((u) => /^\/document-types\/[^/]+$/.test(u.pathname), { timeout: 60_000 }).catch(() => undefined);
      const doc = new URL(page.url()).pathname;
      await resources();
      await page.screenshot({ path: join(SHOTS, 'resources-added-1280-light.png') });
      check('3 adding the document type opens its copy in Document types', /^\/document-types\/[^/]+$/.test(doc), { doc });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  // The copied agent is granted the plugin's tools, which agents-service checks against this tools-service.
  { platform: true, tools: { gateway: true, env: { OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify([FOLDER]) } } },
);

finish();
