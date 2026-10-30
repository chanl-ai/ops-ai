// uc-018 create, publish an agent and chat with it, ui layer: docs/usecases/agents-service/agent-create-publish-chat.md.
// Headless Chromium against a console whose Agents, Workflows and Cases call the agents service on the scripted model;
// chatting with the agent is a conversation in Chat (agents are not offered by Workflows' Start run).
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_ops' };
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const NAME = `Payee Checker ${Math.random().toString(36).slice(2, 6)}`;

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    // The dev console works in team_platform until a team is picked; this script's rows are in team_ops.
    await page.addInitScript(() => sessionStorage.setItem('ops-team', 'team_ops'));
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    await page.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('button', { name: 'New agent' }).first().click({ timeout: 120_000 });
    const dialog = page.getByRole('dialog', { name: 'New agent' });
    await dialog.getByLabel('Name').fill(NAME);
    await dialog.getByLabel('Role').fill('Checks new payees');
    // The Model list is the set publish accepts, so the default alias passes the publish check below (422 otherwise).
    const aliases = (await (await fetch(`${agents}/v1/model-aliases`, { headers: TEAM })).json()).data?.map((a) => a.name) ?? [];
    await dialog.getByRole('combobox', { name: 'Model' }).click();
    const offeredModels = await page.getByRole('option').allInnerTexts();
    await page.keyboard.press('Escape');
    check('the Model list offers exactly the aliases publish accepts', aliases.length > 0 && JSON.stringify(offeredModels) === JSON.stringify(aliases), { offeredModels, aliases });
    const stated = await dialog.getByText(/^Starts as a draft owned by/).innerText();
    const created = page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/agents`, { timeout: 60_000 });
    await dialog.getByTestId('new-agent-submit').click();
    const createRes = await created;
    const agent = (await createRes.json()).data;
    // A new agent belongs to the team the person works as (c-171): the server takes it from the caller's token and team,
    // never from the body, and the console names it from the person's teams list.
    const ownTeam = (await page.getByRole('button', { name: /^Team: .+\. Switch team$/ }).first().getAttribute('aria-label'))?.replace(/^Team: (.+)\. Switch team$/, '$1');
    const sent = JSON.parse(createRes.request().postData() ?? '{}');
    const actingTeam = createRes.request().headers()['x-team-id'];
    check('the new agent is owned by the current team, and the request names no owner', !!ownTeam && !('owner' in sent) && !!actingTeam && agent?.teamId === actingTeam && stated.includes(`owned by ${ownTeam}`), { teamId: agent?.teamId, actingTeam, sent, ownTeam, stated });
    check('New agent creates a draft in the registry (201, not published)', createRes.status() === 201 && agent?.availability === 'not_published', { status: createRes.status(), availability: agent?.availability });
    const opened = await page.waitForURL(`**/agents/${agent?.id}`, { timeout: 60_000 }).then(() => true, () => false);
    const header = await page.getByText(/ · used in \d+ workflow/).first().innerText({ timeout: 30_000 }).catch(() => '');
    check('the agent page names its team from the teams list', !!ownTeam && header.startsWith(`${ownTeam} · used in`), { header, ownTeam });
    check('the agent page opens on the new record', opened && (await page.getByTestId('page-title').first().innerText()) === NAME);

    // Non-vacuous pair with the run below: before the publish the agent has no graph, so a thread on it is refused.
    const early = await fetch(`${agents}/v1/threads`, { method: 'POST', headers: { ...TEAM, 'Content-Type': 'application/json' }, body: JSON.stringify({ graph: `agent:${agent?.id}` }) });
    check('a thread on the draft agent is refused', early.status >= 400, early.status);

    // Grant lookup_account from the runtime's catalogue: the picker lists GET /v1/tools and nothing else.
    const catalogue = (await (await fetch(`${agents}/v1/tools`, { headers: TEAM })).json()).data.map((t) => t.id).sort();
    // The tools picker (EntityPicker, c-135) searches the runtime's catalogue on the server, a page at a time.
    const optioned = armed(page.waitForResponse((r) => r.request().method() === 'GET' && r.url().startsWith(`${agents}/v1/tools/options`), { timeout: 60_000 }));
    await page.getByTestId('agent-tools-picker').getByRole('button', { name: 'Grant tools' }).click();
    const served = (await (await optioned)?.json())?.data?.data ?? [];
    const options = page.getByRole('option');
    await options.first().waitFor({ timeout: 30_000 });
    const shown = await options.allInnerTexts();
    check('the tool picker shows the options route page, every id from the runtime catalogue', served.length > 0 && shown.length === served.length && served.every((o, i) => shown[i].startsWith(o.label) && catalogue.includes(o.id)), { shown, served: served.map((o) => o.id) });
    // Published workflows an agent can start come from the same catalogue, hinted "Workflows".
    const workflows = served.filter((o) => o.hint === 'Workflows');
    check('published workflows are offered, hinted as Workflows', workflows.length > 0 && workflows.every((o) => shown.some((t) => t.startsWith(o.label) && t.includes('Workflows'))), { workflows: workflows.map((o) => o.id) });
    await page.getByPlaceholder('Search tools by name or system…').fill('lookup_account');
    // The draft saves itself a second after the change (c-172): no Save dialog, no note, and the same version.
    const patched = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${agent?.id}`, { timeout: 60_000 }));
    await page.getByRole('option', { name: /^lookup_account\b/ }).first().click({ timeout: 30_000 });
    await page.keyboard.press('Escape');
    const patchRes = await patched;
    const saved = patchRes ? (await patchRes.json()).data : undefined;
    const status = await page.getByTestId('agent-save-status').filter({ hasText: /^Draft v1 saved$/ }).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
    const dialogs = await page.getByRole('dialog').count();
    check('the grant autosaves into the one draft, v1, with no save dialog', patchRes?.status() === 200 && saved?.version === 1 && JSON.stringify(saved?.toolIds) === '["lookup_account"]' && status && dialogs === 0, { status: patchRes?.status(), version: saved?.version, toolIds: saved?.toolIds, shown: status, dialogs });

    await page.getByTestId('request-agent-publish').click();
    const publish = page.getByRole('dialog', { name: /^(Request publish of|Publish) v/ });
    await publish.getByLabel('What changed').fill('First publish');
    const requested = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/agents/${agent?.id}/publish-requests`), { timeout: 60_000 });
    await publish.getByRole('button', { name: /^(Request publish|Publish)$/ }).click();
    const pubRes = await requested;
    const review = (await pubRes.json()).data;
    check('Request publish opens an approved agent_publish review (dev auto-approve)', pubRes.status() === 201 && review?.kind === 'agent_publish' && review?.status === 'approved', { status: pubRes.status(), kind: review?.kind, state: review?.status });

    await page.reload({ waitUntil: 'networkidle' });
    check('after the publish the header no longer offers Request publish', (await page.getByTestId('request-agent-publish').count()) === 0);
    // An edit after publish opens v2 as the draft; the history lists the draft and the published v1 only (c-172).
    const reopened = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${agent?.id}`, { timeout: 60_000 }));
    await page.locator('#ag-role').fill('Checks new payees twice');
    const after = reopened ? (await (await reopened)?.json())?.data : undefined;
    const history = (await (await fetch(`${agents}/v1/agents/${agent?.id}/versions`, { headers: TEAM })).json()).data ?? [];
    check('an edit after publish opens draft v2 and history lists v2 and v1', after?.version === 2 && after?.publishedVersion === 1 && JSON.stringify(history.map((v) => [v.version, v.state])) === '[[2,"draft"],[1,"published"]]', { version: after?.version, history: history.map((v) => [v.version, v.state]) });
    const graphs = (await (await fetch(`${agents}/v1/graphs`, { headers: TEAM })).json()).data.map((g) => g.name);
    check('its wrapper graph is listed by the runtime', graphs.includes(`agent:${agent?.id}`), graphs);

    // A published agent is talked to in Chat; Workflows' Start run lists workflows only (owner decision, 2026-10-18).
    await page.goto(`${consoleUrl}/chat?agent=${agent?.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const box = page.getByLabel('Message');
    await box.waitFor({ timeout: 120_000 });
    await box.fill('Look up account CHQ-2219');
    const messaged = page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 });
    await page.getByRole('button', { name: 'Send' }).click();
    const chatRes = await messaged;
    check('the message reaches a conversation with the published agent', chatRes.status() < 300, chatRes.status());
    // The scripted model answers "Here is what I found." only after lookup_account returns; without the grant it answers
    // "I could not find that.", so the reply on the page shows the granted tool ran.
    const answered = await page.getByText('Here is what I found.').first().waitFor({ timeout: 120_000 }).then(() => true, () => false);
    check('the agent read the account with its granted tool and answered in the conversation', answered && (await page.getByText('I could not find that.').count()) === 0);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
