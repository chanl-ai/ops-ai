// uc-agents-1 an agent's tools are chosen by app, ui layer: docs/usecases/agents-service/an-agents-tools-are-chosen-by-app.md,
// steps 8 to 13. Headless Chromium against a console whose agent page calls the agents service on the scripted model,
// with its fixture tools under several systems. A builder opens Add tools on a new agent, searches for a tool, opens
// its app, selects all of the app's tools and adds them; the Tools section then shows one row for the app and the
// draft can still be published. A granted agent that is then paused is no longer offered, and its grant stays on the
// page with Remove.
import { AGENTS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { saveAgent } from '../../lib/agent_save.mjs';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
const SHOTS = evidenceDir('uc-agents-1', 'ui');
mkdirSync(SHOTS, { recursive: true });
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const read = async (path) => (await (await fetch(`${agents}${path}`, { headers: TEAM })).json()).data;
const post = (path, body) => fetch(`${agents}${path}`, { method: 'POST', headers: TEAM, body: JSON.stringify(body) });
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
    // One picture at each width the console is checked at, then back to the desktop width the steps run at.
    const shoot = async (name) => {
      for (const [width, height] of [[390, 844], [1440, 900]]) {
        await page.setViewportSize({ width, height });
        await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`) });
      }
    };
    const patches = [];
    page.on('request', (r) => r.method() === 'PATCH' && r.url() === `${agents}/v1/agents/${agent.id}` && patches.push(JSON.parse(r.postData() ?? '{}')));
    const appsRead = (search) => armed(page.waitForResponse((r) => r.request().method() === 'GET' && new URL(r.url()).pathname === appsPath && (search === undefined || new URL(r.url()).searchParams.get('search') === search), { timeout: 60_000 }));

    await page.goto(`${consoleUrl}/build/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const trigger = page.getByTestId('agent-tools-picker');
    await trigger.first().waitFor({ timeout: 120_000 });

    // 8 Add tools opens the picker on the apps the server lists for this agent.
    const firstRead = appsRead();
    const isButton = (await trigger.first().evaluate((el) => el.tagName)) === 'BUTTON';
    await (isButton ? trigger.first() : trigger.getByRole('button').first()).click();
    const served = (await (await firstRead)?.json())?.data?.data ?? [];
    const search = page.getByTestId('tools-picker-search');
    const cardsShown = (await seen(search)) && (await Promise.all(served.map((a) => seen(page.getByTestId(`tools-app-${a.id}`), 15_000)))).every(Boolean);
    check('8 Add tools opens a picker with a card for each app the server lists, none granted yet', served.length > 1 && cardsShown && served.every((a) => a.toolsGranted === 0), { served: served.map((a) => [a.id, a.toolsGranted]), cardsShown });

    // 9 Typing a tool's name searches on the server: its app stays, with the tool under it, and the others go.
    const searched = appsRead(word);
    await search.fill(word);
    const hits = (await (await searched)?.json())?.data?.data ?? [];
    const app = hits.find((a) => a.name === system);
    const others = served.filter((a) => !hits.some((h) => h.id === a.id));
    const card = page.getByTestId(`tools-app-${app?.id}`);
    const kept = !!app && (await seen(card));
    const gone = others.length > 0 && (await Promise.all(others.map((a) => page.getByTestId(`tools-app-${a.id}`).first().waitFor({ state: 'detached', timeout: 15_000 }).then(() => true, () => false)))).every(Boolean);
    const match = app?.matches?.[0];
    // A team's own tool may be shown by its name in words ("get_account" reads "Get account"), a plugin's by its title.
    const esc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const shownAs = match && new RegExp(`^(${[match.label, match.id, match.id.replace(/_/g, ' ')].map(esc).join('|')})$`, 'i');
    const named = !!match && (await seen(page.getByRole('dialog').getByText(shownAs), 15_000));
    check('9 searching a tool finds its app on the server, lists the tool under it and drops the other apps', kept && gone && named, { hits: hits.map((a) => a.id), kept, gone, named, match });

    // 10 Opening the app lists its tools; Select all offers to add every one of them.
    const toolsRead = armed(page.waitForResponse((r) => r.request().method() === 'GET' && decodeURIComponent(new URL(r.url()).pathname) === `${appsPath}/${app?.id}/tools` && !new URL(r.url()).searchParams.get('search'), { timeout: 60_000 }));
    await card.first().click();
    // The app's whole list is wanted: a search field that still holds the typed word is cleared.
    if (await search.first().inputValue({ timeout: 5_000 }).catch(() => '')) await search.first().fill('');
    const offered = ((await (await toolsRead)?.json())?.data?.data ?? []).map((t) => t.id).sort();
    await page.getByTestId('tools-app-select-all').click({ timeout: 30_000 });
    const add = page.getByTestId('tools-app-add');
    const label = (await add.innerText({ timeout: 15_000 }).catch(() => '')).trim();
    // One width here: a run that resized to 390 and back at this point found the picker without its Add button.
    await page.screenshot({ path: join(SHOTS, 'app-tools-selected-1440.png') });
    check('10 the app lists its own tools, and Select all offers to add all of them', JSON.stringify(offered) === JSON.stringify(wanted) && label === `Add ${wanted.length} tools`, { offered, wanted, label });

    // 11 Add grants them in one save of the agent's stored tools.
    const saved = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${agent.id}`, { timeout: 60_000 }));
    await add.click();
    const patchRes = await saved;
    const stored = patchRes ? ((await patchRes.json()).data?.toolIds ?? []).slice().sort() : [];
    const row = page.getByTestId(`agent-tools-app-${app?.id}`);
    const rowShown = await seen(row);
    const sends = patches.filter((p) => Array.isArray(p.toolIds));
    check('11 Add grants every selected tool in one save', patchRes?.status() === 200 && JSON.stringify(stored) === JSON.stringify(wanted) && sends.length === 1, { status: patchRes?.status(), stored, saves: sends.length });

    // 12 The Tools section groups the grants under the app, counted as the server counts them, and Publish stays usable.
    const after = (await read(`${appsPath}?granted=true&limit=100`)).data ?? [];
    const counted = after.find((a) => a.id === app?.id);
    const rowText = rowShown ? (await row.first().innerText()).replace(/\s+/g, ' ') : '';
    const oneRow = (await page.locator('[data-testid^="agent-tools-app-"]').count()) === after.length;
    const publish = page.getByTestId('request-agent-publish');
    // Polled, since the page marks itself saved a moment after the save answers.
    const usable = await publish.first().waitFor({ timeout: 30_000 }).then(() => page.waitForFunction(() => document.querySelector('[data-testid="request-agent-publish"]')?.disabled === false, null, { timeout: 30_000 })).then(() => true, () => false);
    await shoot('agent-tools-by-app');
    check('12 the Tools section shows one row for the app with its granted count, and Publish is not disabled', after.length === 1 && oneRow && rowText.includes(system) && rowText.includes(`${wanted.length} of ${wanted.length} tools`) && counted?.toolsGranted === wanted.length && usable, { rowText, counted, rows: after.length, oneRow, usable });

    // 13 A second agent, live, is granted as a tool and then paused: nothing offers it any more, and its grant stays
    // on the page with Remove, so the header's count is the number of tools a person can remove.
    const helper = (await (await post('/v1/agents', { name: `Helper ${Math.random().toString(36).slice(2, 6)}`, role: 'Helps' })).json()).data;
    const live = await post(`/v1/agents/${helper?.id}/publish-requests`, { version: helper?.version, note: 'uc-agents-1' });
    const grant = `agent:${helper?.id}`;
    const both = await saveAgent(agents, TEAM, agent.id, { toolIds: [...wanted, grant] });
    const paused = await post(`/v1/agents/${helper?.id}/paused`, { paused: true });
    if (live.status !== 201 || both.status !== 200 || paused.status !== 200) throw new Error(`setup: publish ${live.status}, grant ${both.status}, pause ${paused.status}`);
    const offered13 = (await read(`/v1/tools/options?ids=${encodeURIComponent(grant)}`)).data ?? [];
    const held = (await read(`/v1/agents/${agent.id}`)).toolIds ?? [];
    await page.reload({ waitUntil: 'domcontentloaded' });
    const section = page.getByTestId('agent-tools-rows');
    await seen(section, 60_000);
    for (const a of (await read(`${appsPath}?granted=true&limit=100`)).data ?? []) {
      await section.getByRole('button', { name: `Show ${a.name} tools` }).click({ timeout: 15_000 }).catch(() => undefined);
      await seen(page.getByTestId(`agent-tools-app-${a.id}-tools`), 15_000);
    }
    const removable = await section.getByRole('button', { name: /^Remove / }).count();
    const counted13 = Number((await page.getByTestId('agent-tools-count').first().innerText().catch(() => '')).trim());
    await shoot('agent-tools-paused-grant');
    check('13 a granted agent that was paused is still on the page with Remove, and the header counts the tools drawn', offered13.length === 0 && held.includes(grant) && removable === held.length && counted13 === held.length, { offered: offered13.length, held: held.length, removable, header: counted13 });

    // The Tools section at a phone's width: the page does not scroll sideways.
    await page.setViewportSize({ width: 390, height: 844 });
    const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    check('the Tools section fits a 390 wide screen', fits && (await seen(row, 10_000)), { fits });
    await page.getByTestId('agent-tools-picker').first().click();
    const phonePicker = await seen(page.getByTestId(`tools-app-${app?.id}`), 30_000);
    await page.screenshot({ path: join(SHOTS, 'picker-apps-390.png') });
    check('the picker opens on its apps at 390 wide', phonePicker && (await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)));
    await page.keyboard.press('Escape');

    check('no page errors', errors.length === 0, errors.slice(0, 3));
  } finally {
    await browser.close();
  }
});

finish();
