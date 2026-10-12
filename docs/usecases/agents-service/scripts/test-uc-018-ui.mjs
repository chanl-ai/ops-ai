// uc-018 create, publish an agent and chat with it, ui layer: docs/usecases/agents-service/agent-create-publish-chat.md.
// Headless Chromium against a console whose Agents, Workflows and Cases call the agents service on the scripted model;
// chatting with the agent is a run of its own graph, agent:<id>, started from the Start run picker.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_all' };
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const NAME = `Payee Checker ${Math.random().toString(36).slice(2, 6)}`;

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
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
    const created = page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/agents`, { timeout: 60_000 });
    await dialog.getByTestId('new-agent-submit').click();
    const createRes = await created;
    const agent = (await createRes.json()).data;
    check('New agent creates a draft in the registry (201, not published)', createRes.status() === 201 && agent?.availability === 'not_published', { status: createRes.status(), availability: agent?.availability });
    const opened = await page.waitForURL(`**/agents/${agent?.id}`, { timeout: 60_000 }).then(() => true, () => false);
    check('the agent page opens on the new record', opened && (await page.getByTestId('page-title').first().innerText()) === NAME);

    // Non-vacuous pair with the run below: before the publish the agent has no graph, so a thread on it is refused.
    const early = await fetch(`${agents}/v1/threads`, { method: 'POST', headers: { ...TEAM, 'Content-Type': 'application/json' }, body: JSON.stringify({ graph: `agent:${agent?.id}` }) });
    check('a thread on the draft agent is refused', early.status >= 400, early.status);

    // Grant lookup_account from the runtime's catalogue: the picker lists GET /v1/tools and nothing else.
    const catalogue = (await (await fetch(`${agents}/v1/tools`, { headers: TEAM })).json()).data.map((t) => t.id).sort();
    await page.getByRole('button', { name: 'Grant tools' }).click();
    const grant = page.getByRole('dialog', { name: 'Grant tools' });
    await grant.locator('[id^="grant-"]').first().waitFor({ timeout: 30_000 });
    const picked = (await grant.locator('[id^="grant-"]').evaluateAll((els) => els.map((e) => e.id.replace('grant-', '')))).sort();
    check('the tool picker offers exactly the runtime catalogue', picked.length > 0 && JSON.stringify(picked) === JSON.stringify(catalogue), { picked, catalogue });
    await grant.locator('#grant-lookup_account').click();
    await grant.getByRole('button', { name: 'Save grants' }).click();
    await page.getByTestId('unsaved-bar').getByRole('button', { name: /^Save as v/ }).click();
    const saving = page.getByRole('dialog', { name: /^Save as v/ });
    const patched = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${agent?.id}`, { timeout: 60_000 }));
    await saving.getByRole('button', { name: /^Save v/ }).click();
    const patchRes = await patched;
    const saved = patchRes ? (await patchRes.json()).data : undefined;
    check('saving the grant makes draft v2 with lookup_account', patchRes?.status() === 200 && saved?.version === 2 && JSON.stringify(saved?.toolIds) === '["lookup_account"]', { status: patchRes?.status(), version: saved?.version, toolIds: saved?.toolIds });

    await page.getByTestId('request-agent-publish').click();
    const publish = page.getByRole('dialog', { name: /Request publish of v/ });
    await publish.getByLabel('What changed').fill('First publish');
    const requested = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/agents/${agent?.id}/publish-requests`), { timeout: 60_000 });
    await publish.getByRole('button', { name: 'Request publish' }).click();
    const pubRes = await requested;
    const review = (await pubRes.json()).data;
    check('Request publish opens an approved agent_publish review (dev auto-approve)', pubRes.status() === 201 && review?.kind === 'agent_publish' && review?.status === 'approved', { status: pubRes.status(), kind: review?.kind, state: review?.status });

    await page.reload({ waitUntil: 'networkidle' });
    check('after the publish the header no longer offers Request publish', (await page.getByTestId('request-agent-publish').count()) === 0);
    const graphs = (await (await fetch(`${agents}/v1/graphs`, { headers: TEAM })).json()).data.map((g) => g.name);
    check('its wrapper graph is listed by the runtime', graphs.includes(`agent:${agent?.id}`), graphs);

    // Chat on a published agent is a thread on its own graph; the Start run picker offers it by name.
    await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
    const start = page.getByRole('dialog', { name: 'Start a run' });
    await start.getByRole('combobox', { name: 'Workflow' }).click();
    const offered = await page.getByRole('option', { name: NAME }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('the Start run picker offers the published agent by name', offered);
    if (offered) await page.getByRole('option', { name: NAME }).click();
    await start.getByLabel('Message').fill('Look up account CHQ-2219');
    const threadMade = page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/threads`, { timeout: 60_000 });
    const streamed = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/threads\/[^/]+\/runs\/stream$/.test(r.url()), { timeout: 120_000 });
    await start.getByTestId('start-run-submit').click();
    const threadRes = await threadMade;
    const tid = (await threadRes.json()).data?.threadId;
    check('the run is a thread on agent:<id>', threadRes.status() === 201 && JSON.parse(threadRes.request().postData() ?? '{}').graph === `agent:${agent?.id}`, threadRes.status());
    check('the run streamed (200)', (await streamed).status() === 200);
    // The dialog reads the stream to its end first. An agent's own runs are not cases, so it reports the finished run
    // instead of opening Cases, and the state is final once the notice shows.
    const finished = await page.getByText('Run finished').first().waitFor({ timeout: 120_000 }).then(() => true, () => false);
    const named = finished && (await page.getByText(`Thread ${tid} ran to its end`, { exact: false }).count()) > 0;
    check('the console reports the finished run by thread id and stays out of Cases', named && !page.url().includes('/cases'), page.url());
    const state = (await (await fetch(`${agents}/v1/threads/${tid}/state`, { headers: TEAM })).json()).data;
    // The scripted model answers "Here is what I found." only after lookup_account returns; without the grant it answers
    // "I could not find that.", so the reply shows the granted tool ran.
    check('the agent read the account with its granted tool and answered', state?.values?.reply === 'Here is what I found.', state?.values);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
