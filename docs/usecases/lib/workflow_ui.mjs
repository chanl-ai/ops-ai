// What the workflow-engine ui scripts share (c-553): a person's headers from a platform sign-in, saving and starting a
// workflow through agents-service as a builder would from the editor, and reading a run back from its console page as
// a person sees it, never from the API, so each check proves the page shows what the run did.
import { AGENTS_PORT, PLATFORM_PORT } from '@ops-ai/usecase-runner/harness';

export const agents = `http://127.0.0.1:${AGENTS_PORT}`;
export const PASSWORD = 'northfield-demo';
export const JAMES = 'j.richardson@harborpine.example';
export const PRIYA = 'p.shah@harborpine.example';
export const MAYA = 'm.okafor@harborpine.example';
const SETTLED = ['succeeded', 'failed', 'cancelled'];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Headers for `email` signed in through platform-service, acting in `team`. */
export async function as(email, team = 'team_ops') {
  const r = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) });
  const token = (await r.json()).data?.token;
  if (!token) throw new Error(`signing ${email} in: ${r.status}`);
  return { Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' };
}

/** Polls `probe` once a second until it returns something truthy, or `seconds` pass (then undefined). */
export async function until(probe, seconds = 90) {
  for (const end = Date.now() + seconds * 1000; Date.now() < end; await sleep(1000)) {
    const got = await probe().catch(() => undefined);
    if (got) return got;
  }
  return undefined;
}

async function call(method, path, headers, body) {
  const r = await fetch(`${agents}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
}

/** Saves a workflow from YAML or a definition object and asks to publish it; `live` is true once it is approved. */
export async function saveAndPublish(headers, source) {
  const saved = await call('POST', '/v1/workflows/definitions', headers, typeof source === 'string' ? { yaml: source } : { definition: source });
  const id = saved.data?.id ?? (typeof source === 'string' ? /\nid: (\S+)/.exec(source)?.[1] : source.id);
  const asked = saved.status === 201 ? await call('POST', `/v1/workflows/definitions/${id}/publish-requests`, headers, {}) : { status: 0 };
  return { id, saved, live: asked.data?.status === 'approved', asked };
}

/** Starts `workflowId` with `input` and returns its run id. */
export async function start(headers, workflowId, input, extra = {}) {
  const r = await call('POST', '/v1/runs', headers, { workflowId, input, ...extra });
  if (!r.data?.runId) throw new Error(`starting ${workflowId}: ${r.status} ${JSON.stringify(r.data).slice(0, 300)}`);
  return r.data.runId;
}

/** The run once it has finished, or is waiting when `orWaiting` is set. */
export function settled(headers, runId, { orWaiting = false, seconds = 120 } = {}) {
  return until(async () => {
    const r = (await call('GET', `/v1/runs/${runId}`, headers)).data;
    return r && (SETTLED.includes(r.status) || (orWaiting && r.status === 'waiting')) ? r : undefined;
  }, seconds);
}

/**
 * Opens a run's console page and reads what it shows: the status badge, the outcome, the waiting notice, every row of
 * its Steps table by node id in order, and the runs it started.
 */
export async function readRunPage(page, consoleUrl, runId) {
  await page.goto(`${consoleUrl}/workflows/runs/${runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('run-status').waitFor({ timeout: 60_000 });
  await page.getByTestId('run-step').first().waitFor({ timeout: 30_000 }).catch(() => undefined);
  const steps = await page.getByTestId('run-step').evaluateAll((els) => els.map((e) => ({ nodeId: e.getAttribute('data-node-id'), name: e.textContent?.trim() })));
  const result = page.getByTestId('run-result');
  return {
    status: (await page.getByTestId('run-status').innerText()).trim(),
    outcome: (await result.count()) ? await result.getAttribute('data-outcome') : null,
    waiting: (await page.getByTestId('run-waiting').count()) ? (await page.getByTestId('run-waiting').innerText()).trim() : null,
    steps,
    // The runs it started, in item order, by the run each row links to.
    children: await page.locator('[data-testid^="run-children-"][data-testid$="-run"]').evaluateAll((els) => els.map((e) => decodeURIComponent(e.getAttribute('href')?.split('/').pop() ?? ''))),
    count: (nodeId) => steps.filter((s) => s.nodeId === nodeId).length,
  };
}

/**
 * Decides a run's waiting step in Human Tasks as the signed-in person: opens the task, picks the option, presses
 * Decide, confirms with the password when asked, and returns the decision's HTTP status, or 0 when none was sent.
 */
export async function decideInConsole(page, consoleUrl, run, option = 'approve') {
  const review = `${run.id}:${run.waiting.node}:${run.waiting.iteration ?? 1}`;
  await page.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(review)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  return decideOpenTask(page, option);
}

/**
 * Decides the task Human Tasks has open as the signed-in person: picks the option, fills its inputs by the start of
 * their labels (`{ Amount: 1500 }`), presses Decide, confirms with the password when asked, and returns the decision's
 * HTTP status, or 0 when none was sent.
 */
export async function decideOpenTask(page, option = 'approve', inputs = {}) {
  await page.getByTestId('decision-panel').waitFor({ timeout: 60_000 }).catch(async (e) => {
    const shown = (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 500);
    throw new Error(`no decision panel on ${page.url()}: ${e.message.split('\n')[0]}; the page shows: ${shown}`);
  });
  const decision = () => page.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 90_000 }).catch(() => undefined);
  const sent = decision();
  await page.getByTestId(`option-${option}`).click();
  for (const [label, value] of Object.entries(inputs)) {
    await page.getByTestId(`option-inputs-${option}`).getByLabel(new RegExp(`^${label}`, 'i')).fill(String(value));
  }
  await page.getByTestId('decide').click();
  // A step-up policy asks the person to confirm it is them: before the decision is sent, or once the decision answers
  // 422 step_up_required, after which the console sends it again.
  const reauth = page.getByRole('dialog').filter({ hasText: /Confirm it/i });
  const first = await Promise.race([sent.then((r) => ({ r })), reauth.waitFor({ timeout: 90_000 }).then(() => ({ asked: true }))]).catch(() => ({}));
  if (!first.asked && first.r?.status() !== 422) return first.r?.status() ?? 0;
  if (first.r) await reauth.waitFor({ timeout: 30_000 });
  const retried = first.r ? decision() : sent;
  await reauth.getByLabel(/password/i).first().fill(PASSWORD);
  await reauth.getByRole('button', { name: /confirm|sign in|continue/i }).last().click();
  return (await retried)?.status() ?? 0;
}

/**
 * Turns a per-team switch on from Govern › Policies as the signed-in person (a team admin): picks On on the policy's
 * card, saves it, and returns the save's HTTP status, or 0 when none was sent.
 */
export async function turnOnPolicy(page, consoleUrl, key) {
  return setPolicy(page, consoleUrl, key, 'true');
}

/**
 * Picks `choice` on a policy's card in Govern › Policies as the signed-in person (`true`, a floor such as `0.95`) and
 * saves it; returns the save's HTTP status, or 0 when none was sent.
 */
export async function setPolicy(page, consoleUrl, key, choice) {
  await page.goto(`${consoleUrl}/settings/policies`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const card = page.getByTestId(`setting-policy-${key}`);
  await card.waitFor({ timeout: 60_000 });
  const saved = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().includes(`/v1/policies/${key}`), { timeout: 30_000 }).then((r) => r.status(), () => 0);
  await card.locator(`label[for="${key}-${choice}"]`).click();
  await card.getByRole('button', { name: 'Save' }).click();
  return saved;
}

/**
 * Opens a step's sheet from the run page's Steps table (the run page must be open) and reads what it shows: the port
 * it left by and its Output block, parsed from the JSON the page prints.
 */
export async function readStepSheet(page, nodeId, nth = 0) {
  await page.locator(`[data-testid="run-step"][data-node-id="${nodeId}"]`).nth(nth).click();
  const sheet = page.getByTestId('run-step-sheet');
  await sheet.waitFor({ timeout: 30_000 });
  const blocks = sheet.getByTestId('json-block');
  await blocks.nth(1).waitFor({ timeout: 15_000 });
  const text = (await blocks.nth(1).locator('pre').innerText()).trim();
  let output;
  try {
    output = JSON.parse(text);
  } catch {
    output = text;
  }
  // textContent, not innerText: the label is drawn in capitals, and innerText returns what is drawn.
  const shown = (await sheet.textContent()) ?? '';
  const port = /Port taken\s*([\w-]+?)\s*Attempts/.exec(shown)?.[1] ?? '';
  const attempts = Number(/Attempts\s*(\d+)/.exec(shown)?.[1] ?? NaN);
  await page.keyboard.press('Escape');
  await sheet.waitFor({ state: 'hidden', timeout: 10_000 }).catch(() => undefined);
  return { port, attempts, output };
}

/** The stack the AI step ui scripts share: platform sign-in, models-service on the fake OpenAI's ai-steps rules. */
export const AI_STACK = { platform: true, demo: true, fakeModelRules: 'services/agents-service/tests/fixtures/ai-steps-fake-openai' };

/** A request-triggered workflow of `steps`, wired `[from, port, to]`; every end is an outcome named after it. */
export function aiDefinition(id, steps, wires) {
  const ends = [...new Set(wires.map(([, , to]) => to).filter((to) => to.startsWith('end_')))].sort();
  return {
    schemaVersion: 2,
    id,
    name: id,
    nodes: [
      { id: 'start', type: 'ops.trigger.request', typeVersion: 1, parameters: {} },
      ...steps,
      ...ends.map((e) => ({ id: e, type: 'ops.flow.end', typeVersion: 1, parameters: { outcome: e.slice(4) } })),
    ],
    connections: wires.map(([from, port, to]) => ({ from: { node: from, port }, to: { node: to, port: 'in' } })),
  };
}

/**
 * Grants each operation through the agent page's tools picker (EntityPicker, c-135): open, search, pick, signed in as
 * `email`. agents-service reads the tool directory through a 30-second cache, so an operation published moments ago is
 * offered only once that cache turns over; the script waits for the options route to offer it (up to 60 s) before
 * searching, so the picker's first search finds it.
 */
export async function grantTools(page, ops, email) {
  const H = await as(email);
  const picker = page.getByTestId('agent-tools-picker');
  for (const op of ops) {
    const offered = await until(async () => {
      const r = await fetch(`${agents}/v1/tools/options?search=${encodeURIComponent(op)}`, { headers: H });
      return ((await r.json()).data?.data ?? []).some((o) => o.id === op);
    }, 60);
    if (!offered) throw new Error(`the tools picker never offered ${op}`);
    await picker.getByRole('button', { name: 'Grant tools' }).click({ timeout: 120_000 });
    await page.getByPlaceholder('Search tools by name or system…').fill(op);
    await page.getByRole('option', { name: new RegExp(`^${op}\\b`) }).first().click({ timeout: 60_000 });
    await page.keyboard.press('Escape');
  }
}

/**
 * Opens a held chat write in Human Tasks as the signed-in approver and returns its decision form. A chat's held write
 * is reviewed under the chat's thread id, so the task opens by that id. Throws, with what the page shows, when the
 * form never appears.
 */
export async function openHeldChatWrite(page, consoleUrl, thread) {
  await page.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(thread ?? '')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const form = page.getByTestId('review-decision-form');
  if (!(await form.waitFor({ timeout: 60_000 }).then(() => true, () => false))) {
    throw new Error(`the held chat write did not open in Human Tasks: ${(await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 300)}`);
  }
  return form;
}
