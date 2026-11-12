// uc-590 a team adds an app's resources as its own copies, ui layer: docs/usecases/agents-service/plugin-templates.md.
// The ui stack with plugins on and the templates desk (services/tools-service/tests/plugin_templates/
// templates_desk), turned on for Operations by Priya through the API. Priya opens the app's
// Resources tab: the agent, skill, workflow and document type each offer Add to team. Adding the agent opens its copy;
// back on the tab it reads Added and Open lands on the same copy; adding the document type opens its copy in Document
// types. Then steps 70 to 76 on the service desk plugin (scripts/resources_desk.py, written for this run): what a viewer
// sees, choosing several, a workflow added before the agent it runs, an update, removing a copy, and the app's knowledge
// source. Screenshots go to evidenceDir('590', 'uc').
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const PLUGIN = 'test.templates';
const APP = `plugin:${PLUGIN}`;
const FOLDER = join(ROOT, 'services/tools-service/tests/plugin_templates/templates_desk');
const SHOTS = evidenceDir('590', 'uc');
const agentsApi = `http://127.0.0.1:${AGENTS_PORT}`;
// The service desk plugin, written per run so a step can change its agent template on disk.
const DESK_DIR = execFileSync('uv', ['run', '--quiet', 'python', join(ROOT, 'docs/usecases/agents-service/scripts/resources_desk.py'), mkdtempSync(join(tmpdir(), 'uc590-ui-'))], { cwd: ROOT, encoding: 'utf8' }).trim();
const DESK = 'plugin:test.resources';

const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const call = async (base, method, path, headers, body) => {
  const r = await fetch(`${base}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  let data;
  try {
    data = JSON.parse(text).data;
  } catch {
    data = undefined;
  }
  return { status: r.status, text: text.slice(0, 300), data };
};
const signIn = async (browser, email) => {
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
  await page.goto(`${consoleUrlOf.url}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};
const consoleUrlOf = { url: '' };
const deskTab = async (page) => {
  await page.goto(`${consoleUrlOf.url}/integrations/apps/${encodeURIComponent(DESK)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('app-tab-resources').click({ timeout: 120_000 });
  await page.getByTestId('app-skills').waitFor({ timeout: 60_000 });
  return page.getByTestId('app-skills');
};

await withUiStack(
  async (consoleUrl) => {
    const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
    const team = await call(tools, 'PUT', `/v1/apps/${encodeURIComponent(APP)}/team`, priya, { enabled: true });
    // A new app hands agents its read tools only; the team admin adds the write the agent template grants.
    await call(tools, 'POST', `/v1/apps/${encodeURIComponent(APP)}/tools`, priya, { tools: ['templates_close_case'] });
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

      // Steps 70 to 76: the service desk.
      consoleUrlOf.url = consoleUrl;
      const desk = await call(tools, 'PUT', `/v1/apps/${encodeURIComponent(DESK)}/team`, priya, { enabled: true });
      // A new app hands agents its read tools only; the team admin adds the write the agent template grants.
      await call(tools, 'POST', `/v1/apps/${encodeURIComponent(DESK)}/tools`, priya, { tools: ['resources_close_ticket'] });
      check('69 set-up: the service desk is on for Operations', desk.status === 200, { desk: desk.text });

      const ravi = await signIn(browser, 'r.menon@harborpine.example');
      ravi.on('pageerror', (e) => errors.push(e.message));
      const viewed = await deskTab(ravi);
      // The grid lets every member keep document types, so only the agent, skill and workflow are a builder's to add.
      let offeredToViewer = 0;
      for (const id of ['ticket-helper', 'close-ticket', 'ticket-triage']) offeredToViewer += await viewed.getByTestId(`resource-add-${id}`).count();
      const viewerWords = ((await viewed.innerText()) ?? '').replace(/\s+/g, ' ');
      await ravi.screenshot({ path: join(SHOTS, 'resources-viewer-1280-light.png') });
      check('70 a viewer sees the four resources, with no Add to team on the agent, skill and workflow, and reads who adds them', (await viewed.locator('[data-testid^="resource-"]').count()) >= 4 && offeredToViewer === 0 && /builder adds/i.test(viewerWords), { offeredToViewer, viewerWords: viewerWords.slice(0, 300) });

      const tab = await deskTab(page);
      const boxes = await tab.getByRole('checkbox').count();
      const addSelected = await page.getByRole('button', { name: /Add selected/ }).count();
      check('71 each resource can be ticked, and Add selected adds the ticked ones together', boxes >= 4 && addSelected === 1, { boxes, addSelected });

      const before = new URL(page.url()).pathname;
      await page.getByTestId('resource-add-ticket-triage').click();
      await page.waitForURL((u) => u.pathname !== before, { timeout: 15_000 }).catch(() => undefined);
      const landed = new URL(page.url()).pathname;
      const told = ((await page.locator('body').innerText()) ?? '').replace(/\s+/g, ' ');
      await page.screenshot({ path: join(SHOTS, 'resources-workflow-alone-1280-light.png') });
      check('72 Add to team on the workflow, before the agent it runs is added, names Ticket helper and opens no workflow', landed === before && /Ticket helper/.test(told), { landed, told: told.slice(0, 300) });
      const strayFlow = landed.match(/^\/workflows\/([^/]+)/)?.[1];
      if (strayFlow) await call(agentsApi, 'DELETE', `/v1/workflows/definitions/${strayFlow}`, priya);

      const helper = await call(agentsApi, 'POST', `/v1/resources/${encodeURIComponent(`${DESK}:ticket-helper`)}/copies`, priya, {});
      const helperFile = join(DESK_DIR, 'templates', 'ticket-helper.yaml');
      writeFileSync(helperFile, readFileSync(helperFile, 'utf8').replace('You help a service agent with one ticket.', 'Read the ticket first.'));
      const updated = await deskTab(page);
      const tabText = ((await updated.innerText()) ?? '').replace(/\s+/g, ' ');
      await page.screenshot({ path: join(SHOTS, 'resources-update-1280-light.png') });
      check('73 an added agent whose template changed reads Update available', helper.status === 201 && /Update available/.test(tabText), { helper: helper.text, tab: tabText.slice(0, 300) });

      const removeOffered = await updated.getByRole('button', { name: /Remove|Delete/ }).count();
      check('74 an added resource offers Remove on its row', removeOffered >= 1, { removeOffered });

      check('75 the app’s help articles are listed as a resource to add to a knowledge base', /Help articles/.test(tabText), { tab: tabText.slice(0, 300) });
      const helperId = helper.data?.copy?.recordId;
      if (helperId) await call(agentsApi, 'DELETE', `/v1/agents/${helperId}`, priya);

      check('76 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  // The copied agent is granted the plugin's tools, which agents-service checks against this tools-service.
  { platform: true, tools: { gateway: true, env: { OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify([FOLDER, DESK_DIR]) } } },
);

finish();
