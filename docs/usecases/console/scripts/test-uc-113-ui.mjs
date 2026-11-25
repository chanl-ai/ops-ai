// uc-113 a builder picks a knowledge base past the first hundred and a tool, searched on the server, ui layer:
// docs/usecases/console/pickers-search-the-server.md. Signed in through platform-service.
import { AGENTS_PORT, KB_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { chooseMatchedTool, findMatchedTool, showHeldTools } from '../../lib/tools_picker.mjs';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const kb = `http://127.0.0.1:${KB_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const armed = (p) => (p.catch(() => undefined), p);
const name = (i) => `Picker ${TAG} ${String(i).padStart(3, '0')}`;

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@harborpine.example')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const bases = [];
    for (let i = 0; i < 120; i++) bases.push(await data(await fetch(`${kb}/v1/knowledge-bases`, { method: 'POST', headers: J, body: JSON.stringify({ name: name(i), owner: 'Operations' }) })));
    const target = bases[117];
    const agent = await data(await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Picker desk ${TAG}`, role: 'Answers from many bases' }) }));

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const asked = [];
      page.on('request', (r) => /\/(options|tool-apps(\/[^?]+\/tools)?)\?/.test(r.url()) && asked.push(r.url()));
      const param = (u, key) => new URL(u).searchParams.get(key);
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });

      // Steps 1-2: the 118th base, found by a server search and picked.
      const knowledge = page.getByTestId('agent-knowledge-picker');
      await knowledge.getByRole('button', { name: 'Add', exact: true }).click({ timeout: 120_000 });
      await page.getByPlaceholder('Search knowledge bases…').fill(name(117));
      const offered = page.getByRole('option', { name: new RegExp(name(117)) });
      await offered.waitFor({ timeout: 30_000 }).catch(() => undefined);
      check('the knowledge picker finds the 118th base through kb-service', (await offered.count()) === 1 && asked.some((u) => u.startsWith(kb) && u.includes('knowledge-bases/options') && new URL(u).searchParams.get('search') === name(117)), { asked: asked.slice(-3) });
      await offered.click();
      await page.keyboard.press('Escape');
      // The chip's name comes from the options route by id, so it lands a moment after the pick.
      await page.getByTestId('agent-knowledge-rows').getByText(name(117)).waitFor({ timeout: 15_000 }).catch(() => undefined);
      check('the picked base shows as a chip with its name', (await page.getByTestId('agent-knowledge-rows').getByText(name(117)).count()) === 1);

      // Step 3: a tool through agents-service's search.
      const tool = await findMatchedTool(page, 'lookup_acc', 'lookup_account');
      await tool.waitFor({ timeout: 30_000 }).catch(() => undefined);
      // The typed words themselves go to agents-service, which names the tool under its app.
      const searches = asked.filter((u) => u.startsWith(agents) && /\/tool-apps\?/.test(u) && param(u, 'search') === 'lookup_acc');
      const offeredTools = await page.locator('[data-testid^="tools-match-"]').count();
      check('the tools picker searches agents-service', (await tool.count()) === 1 && offeredTools >= 1 && searches.length >= 1, { offeredTools, asked: asked.slice(-3) });
      // The draft saves itself a second after a change: there is no Save button, so the save is awaited.
      const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/v1/agents/${agent.id}`), { timeout: 60_000 }));
      await chooseMatchedTool(page, tool);

      // Step 4: the draft autosaves, and the version holds ids.
      await saved;
      await page.getByTestId('agent-save-status').filter({ hasText: /saved$/ }).first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      const stored = await data(await fetch(`${agents}/v1/agents/${agent.id}`, { headers: J }));
      check('the version stores the base id and the tool id', stored.collections?.includes(target.id) && stored.toolIds?.includes('lookup_account'), { collections: stored.collections, toolIds: stored.toolIds });

      // Step 5: chips resolve by id after a reload.
      const before = asked.length;
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByTestId('agent-knowledge-rows').getByText(name(117)).waitFor({ timeout: 60_000 }).catch(() => undefined);
      await showHeldTools(page);
      const held = page.getByTestId('agent-tools-rows').getByText(/^lookup[_ ]account$/i);
      await held.first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      // The base's name comes from the options route by id; the tool's from the agent's own grants, read per app.
      const again = asked.slice(before);
      const toolsRead = again.some((u) => /\/tool-apps\?/.test(u) && param(u, 'granted') === 'true') && again.some((u) => /\/tool-apps\/[^?]+\/tools\?/.test(u) && param(u, 'granted') === 'true');
      check('after a reload the chips show names resolved by id', (await page.getByTestId('agent-knowledge-rows').getByText(name(117)).count()) === 1 && (await held.count()) === 1 && again.some((u) => u.includes('ids=')) && toolsRead, { again: again.slice(-6) });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
