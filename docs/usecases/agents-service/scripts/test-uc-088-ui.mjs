// uc-088 a builder sets the limits callers override within and publishes them with the agent, ui layer:
// docs/usecases/agents-service/agent-limits-published.md. Headless Chromium against a console whose Agents call the
// agents service on the scripted model. The agent page offers only controls the runtime acts on.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_all' };
const armed = (p) => (p.catch(() => undefined), p);
const NAME = `Limits Checker ${Math.random().toString(36).slice(2, 6)}`;
const api = async (path, init = {}) => (await fetch(`${agents}${path}`, { ...init, headers: { ...TEAM, 'Content-Type': 'application/json', ...(init.headers ?? {}) } })).json();

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    // A published agent granted a read and a write tool, made through the API so the page under test is the editor.
    const created = (await api('/v1/agents', { method: 'POST', body: JSON.stringify({ name: NAME, role: 'Checks wires before they leave' }) })).data;
    // Edits save into the one draft (c-172), so the version to publish is the one the edit answers with.
    const edited = (await api(`/v1/agents/${created.id}`, { method: 'PATCH', body: JSON.stringify({ toolIds: ['lookup_account', 'place_wire_hold'], note: 'tools' }) })).data;
    await api(`/v1/agents/${created.id}/publish-requests`, { method: 'POST', body: JSON.stringify({ version: edited.version, note: 'first' }) });

    // Two chats with the agent, so Recent runs has rows to show from the API.
    const chats = [];
    for (let i = 0; i < 2; i++) chats.push((await api('/chat/threads', { method: 'POST', body: JSON.stringify({ agentId: created.id, kbIds: [] }) })).data?.id);
    await page.goto(`${consoleUrl}/agents/${created.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByTestId('agent-limits').waitFor({ timeout: 120_000 });

    // Only what works: chat is the one channel, the tool-call cap the one guardrail setting, and no evals.
    const channels = await page.locator('#ag-channels [role="radio"], #ag-channels button').allInnerTexts();
    check('Can talk on offers Chat alone', JSON.stringify(channels.map((c) => c.trim())) === '["Chat"]', channels);
    // Masking is enforced since c-293, so its switch shows; When unsure is not enforced, so it does not.
    check('only enforced guardrail settings are shown', (await page.locator('#g-pii').count()) === 1 && (await page.locator('#g-unsure').count()) === 0 && (await page.locator('#g-max').count()) === 1);
    check('no Evals tab is offered', (await page.getByTestId('agent-evals-tab-trigger').count()) === 0);
    const runs = (await api(`/v1/agents/${created.id}/runs`)).data ?? [];
    // Recent runs sits in the test panel's Used in tab (c-285).
    await page.getByTestId('agent-test-panel').getByRole('tab', { name: 'Used in' }).click();
    await page.getByTestId('recent-runs-card').locator('li').first().waitFor({ timeout: 30_000 }).catch(() => undefined);
    const rows = await page.getByTestId('recent-runs-card').locator('li').count();
    check('the rail lists the agent\'s recent runs from the API', runs.length === 2 && rows === runs.length && chats.every((t) => runs.some((r) => r.threadId === t)), { rows, runs: runs.map((r) => r.threadId), chats });

    // A temperature default above its highest is refused by the server, naming the limit, and nothing is saved.
    const limits = page.getByTestId('agent-limits');
    // Edits save themselves into the one draft a second after the last change (c-172); each wait is armed first.
    const nextPatch = () => armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${created.id}`, { timeout: 60_000 }));
    const before = (await api(`/v1/agents/${created.id}`)).data.version;
    const refusedP = nextPatch();
    await limits.locator('#lim-temp').click();
    await limits.locator('#lim-temp-max').fill('0.7');
    await limits.locator('#lim-temp-default').fill('0.9');
    await limits.getByLabel('Callers may switch off place_wire_hold').click();
    await limits.locator('#lim-instr').click();
    const refused = await refusedP;
    const refusal = refused ? (await refused.json()).error : undefined;
    check('an out-of-range default is refused with 422 naming limits.temperature.default', refused?.status() === 422 && refusal?.code === 'invalid_limits' && refusal?.message.startsWith('limits.temperature.default'), { status: refused?.status(), refusal });
    const shownError = await page.getByTestId('agent-save-status').filter({ hasText: /^Not saved: limits\.temperature/ }).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('the refused save changed nothing and the page says why', (await api(`/v1/agents/${created.id}`)).data.version === before && shownError, { shownError });
    // A refused draft is not sent again by itself (c-172): only a change or Retry sends it.
    let resent = 0;
    const countPatch = (r) => { if (r.method() === 'PATCH' && r.url() === `${agents}/v1/agents/${created.id}`) resent += 1; };
    page.on('request', countPatch);
    await page.waitForTimeout(4_000);
    const retryP = nextPatch();
    await page.getByTestId('agent-save-retry').click();
    const retried = await retryP;
    page.off('request', countPatch);
    check('a refused draft waits for a change or Retry instead of resending every second', resent === 1 && retried?.status() === 422, { resent, retried: retried?.status() });
    // The refused save and its Retry, kept with the card's evidence; UC088_SHOTS points them anywhere else.
    const shots = process.env.UC088_SHOTS ?? join(process.cwd(), '.codeloop', 'evidence', '088');
    mkdirSync(shots, { recursive: true });
    await page.screenshot({ path: join(shots, 'agent-save-retry.png'), fullPage: false });

    const savedP = nextPatch();
    await limits.locator('#lim-temp-default').fill('0.4');
    const savedRes = await savedP;
    const saved = savedRes ? (await savedRes.json()).data : undefined;
    const want = { min: 0, max: 0.7, default: 0.4 };
    // Over a published version, the first save opens the one draft (c-172): the next version number.
    check('the save opens the draft over the published version, with the limits as set', savedRes?.status() === 200 && saved?.version === before + 1 && JSON.stringify(saved?.limits?.temperature) === JSON.stringify(want) && JSON.stringify(saved?.limits?.switchableToolIds) === '["lookup_account"]' && saved?.limits?.callersMayAddInstructions === true, { before, version: saved?.version, status: savedRes?.status(), limits: saved?.limits });
    const versions = (await api(`/v1/agents/${created.id}/versions`)).data;
    check('the version history names the change', versions[0]?.changes?.includes('Changed caller limits'), versions[0]?.changes);

    // Published through the same review as the agent: the reviewer sees the limits being approved.
    await page.getByTestId('request-agent-publish').click();
    const publish = page.getByRole('dialog', { name: /^(Request publish of|Publish) v/ });
    await publish.getByLabel('What changed').fill('Caller limits');
    const requested = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/agents/${created.id}/publish-requests`), { timeout: 60_000 });
    await publish.getByRole('button', { name: /^(Request publish|Publish)$/ }).click();
    const review = (await (await requested).json()).data;
    check('the publish review carries the limits', JSON.stringify(review?.agentPublish?.limits) === JSON.stringify(saved?.limits), review?.agentPublish?.limits);
    const live = (await api(`/v1/agents/${created.id}`)).data;
    check('the draft that was saved is the published version', live.publishedVersion === saved?.version && JSON.stringify(live.limits) === JSON.stringify(saved?.limits), { publishedVersion: live.publishedVersion, saved: saved?.version });

    // The test panel's Why shows the review the write paused on: a test is a real chat, so it opens the review a run
    // would (c-285). The API's single-turn harness names the same approval, and whether deciding it needs a step-up.
    await page.getByTestId('test-agent-button').click();
    const panel = page.getByTestId('agent-test-panel');
    await panel.getByLabel('Message').fill('Place a 24-hour hold on wire W-88213');
    await panel.locator('button[aria-label="Send"]').click();
    // The submit button reads Stop while the reply streams; the reply has ended when it reads Send again.
    await panel.locator('button[aria-label="Stop"]').waitFor({ timeout: 10_000 }).catch(() => undefined);
    await panel.locator('button[aria-label="Stop"]').waitFor({ state: 'detached', timeout: 120_000 });
    await page.waitForTimeout(1500);
    await panel.getByTestId('why-tab').click();
    const paused = await panel.getByTestId('test-would-pause').first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
    const said = paused ? await panel.getByTestId('test-would-pause').first().innerText() : '';
    const turn = (await api(`/v1/agents/${created.id}/test`, { method: 'POST', body: JSON.stringify({ message: 'Place a 24-hour hold on wire W-88213' }) })).data;
    const would = turn?.wouldPause;
    check('the test panel names the review the write paused on, and its step-up', paused && !!would && said.includes('step-up') === !!would.stepUp, { said, would });
    // Caps are optional numbers: empty is no cap, and a real agent may set a large one.
    const capsSaved = nextPatch();
    await page.locator('#g-max').fill('');
    await page.locator('#g-model-calls').fill('40');
    const caps = (await (await capsSaved)?.json().catch(() => null))?.data?.guardrails;
    check('an empty cap saves as no cap and a large one as itself', caps?.maxToolCallsPerTurn === null && caps?.maxModelCallsPerTurn === 40, caps);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
