// uc-agents-1 an agent's tools are chosen by app, ui layer: docs/usecases/agents-service/an-agents-tools-are-chosen-by-app.md,
// steps 6 to 10. Headless Chromium against a console whose agent page calls the agents service on the scripted model,
// with its fixture tools under several systems. A builder opens Add tools on a new agent, searches for a tool, opens
// its app, selects all of the app's tools and adds them; the Tools section then shows one row for the app and the
// draft can still be published.
import { AGENTS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
const SHOTS = evidenceDir('uc-agents-1', 'ui');
mkdirSync(SHOTS, { recursive: true });
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const read = async (path) => (await (await fetch(`${agents}${path}`, { headers: TEAM })).json()).data;
const seen = (locator, ms = 30_000) => locator.first().waitFor({ timeout: ms }).then(() => true, () => false);

await withUiStack(async (consoleUrl) => {
  const made = await fetch(`${agents}/v1/agents`, { method: 'POST', headers: TEAM, body: JSON.stringify({ name: `Tools by app ${Math.random().toString(36).slice(2, 6)}`, role: 'Reads' }) });
  const agent = (await made.json()).data;
  if (!agent?.id) throw new Error(`setup: the agent was not created (${made.status})`);
  const appsPath = `/v1/agents/${agent.id}/tool-apps`;

  // The app to choose: the system that holds the most of the tools this stack offers, found by one of its tools.
  const own = (await read('/v1/tools?pageSize=200')).data.filter((t) => !/^(workflow|agent):/.test(t.id));
  const bySystem = new Map();
  for (const t of own) bySystem.set(t.server, [...(bySystem.get(t.server) ?? []), t]);
  const [system, tools] = [...bySystem].sort((x, y) => y[1].length - x[1].length)[0];
  const wanted = tools.map((t) => t.id).sort();
  const word = tools[0].name;

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    // The dev console works in team_platform until a team is picked; this script's rows are in team_ops.
    await page.addInitScript(() => sessionStorage.setItem('ops-team', 'team_ops'));
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    const patches = [];
    page.on('request', (r) => r.method() === 'PATCH' && r.url() === `${agents}/v1/agents/${agent.id}` && patches.push(JSON.parse(r.postData() ?? '{}')));
    const appsRead = (search) => armed(page.waitForResponse((r) => r.request().method() === 'GET' && new URL(r.url()).pathname === appsPath && (search === undefined || new URL(r.url()).searchParams.get('search') === search), { timeout: 60_000 }));

    await page.goto(`${consoleUrl}/build/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const trigger = page.getByTestId('agent-tools-picker');
    await trigger.first().waitFor({ timeout: 120_000 });

    // 6 Add tools opens the picker on the apps the server lists for this agent.
    const firstRead = appsRead();
    const isButton = (await trigger.first().evaluate((el) => el.tagName)) === 'BUTTON';
    await (isButton ? trigger.first() : trigger.getByRole('button').first()).click();
    const served = (await (await firstRead)?.json())?.data?.data ?? [];
    const search = page.getByTestId('tools-picker-search');
    const cardsShown = (await seen(search)) && (await Promise.all(served.map((a) => seen(page.getByTestId(`tools-app-${a.id}`), 15_000)))).every(Boolean);
    check('6 Add tools opens a picker with a card for each app the server lists, none granted yet', served.length > 1 && cardsShown && served.every((a) => a.toolsGranted === 0), { served: served.map((a) => [a.id, a.toolsGranted]), cardsShown });

    // 7 Typing a tool's name searches on the server: its app stays, with the tool under it, and the others go.
    const searched = appsRead(word);
    await search.fill(word);
    const hits = (await (await searched)?.json())?.data?.data ?? [];
    const app = hits.find((a) => a.name === system);
    const others = served.filter((a) => !hits.some((h) => h.id === a.id));
    const card = page.getByTestId(`tools-app-${app?.id}`);
    const kept = !!app && (await seen(card));
    const gone = others.length > 0 && (await Promise.all(others.map((a) => page.getByTestId(`tools-app-${a.id}`).first().waitFor({ state: 'detached', timeout: 15_000 }).then(() => true, () => false)))).every(Boolean);
    const match = app?.matches?.[0];
    const named = !!match && (await seen(page.getByRole('dialog').getByText(match.label, { exact: true }), 15_000));
    check('7 searching a tool finds its app on the server, lists the tool under it and drops the other apps', kept && gone && named, { hits: hits.map((a) => a.id), kept, gone, named, match });

    // 8 Opening the app lists its tools; Select all offers to add every one of them.
    const toolsRead = armed(page.waitForResponse((r) => r.request().method() === 'GET' && decodeURIComponent(new URL(r.url()).pathname) === `${appsPath}/${app?.id}/tools`, { timeout: 60_000 }));
    await card.first().click();
    const offered = ((await (await toolsRead)?.json())?.data?.data ?? []).map((t) => t.id).sort();
    await page.getByTestId('tools-app-select-all').click({ timeout: 30_000 });
    const add = page.getByTestId('tools-app-add');
    const label = (await add.innerText({ timeout: 15_000 }).catch(() => '')).trim();
    await page.screenshot({ path: join(SHOTS, 'app-tools-selected-1440.png') });
    check('8 the app lists its own tools, and Select all offers to add all of them', JSON.stringify(offered) === JSON.stringify(wanted) && label === `Add ${wanted.length} tools`, { offered, wanted, label });

    // 9 Add grants them in one save of the agent's stored tools.
    const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${agent.id}`, { timeout: 60_000 }));
    await add.click();
    const patchRes = await saved;
    const stored = patchRes ? ((await patchRes.json()).data?.toolIds ?? []).slice().sort() : [];
    const row = page.getByTestId(`agent-tools-app-${app?.id}`);
    const rowShown = await seen(row);
    const sends = patches.filter((p) => Array.isArray(p.toolIds));
    check('9 Add grants every selected tool in one save', patchRes?.status() === 200 && JSON.stringify(stored) === JSON.stringify(wanted) && sends.length === 1, { status: patchRes?.status(), stored, saves: sends.length });

    // 10 The Tools section groups the grants under the app, counted as the server counts them, and Publish stays usable.
    const after = (await read(`${appsPath}?granted=true&limit=100`)).data ?? [];
    const counted = after.find((a) => a.id === app?.id);
    const rowText = rowShown ? (await row.first().innerText()).replace(/\s+/g, ' ') : '';
    const oneRow = (await page.locator('[data-testid^="agent-tools-app-"]').count()) === after.length;
    const publish = page.getByTestId('request-agent-publish');
    // Polled, since the page marks itself saved a moment after the save answers.
    const usable = await publish.first().waitFor({ timeout: 30_000 }).then(() => page.waitForFunction(() => document.querySelector('[data-testid="request-agent-publish"]')?.disabled === false, null, { timeout: 30_000 })).then(() => true, () => false);
    await page.screenshot({ path: join(SHOTS, 'agent-tools-by-app-1440.png') });
    check('10 the Tools section shows one row for the app with its granted count, and Publish is not disabled', after.length === 1 && oneRow && rowText.includes(system) && rowText.includes(`${counted?.toolsGranted} of ${counted?.toolsTotal} tools`) && counted?.toolsGranted === wanted.length && usable, { rowText, counted, rows: after.length, oneRow, usable });

    check('no page errors', errors.length === 0, errors.slice(0, 3));
  } finally {
    await browser.close();
  }
});

finish();
