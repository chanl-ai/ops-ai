// uc-003 simple workflow started from the console, ui layer: docs/usecases/agents-service/simple-workflow.md.
// Headless Chromium against a console whose Cases runs call the agents service on the scripted model; Workflows lists
// from the mock, and its Start run posts through the cases switch.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const QUESTION = 'What is the daily wire limit for a personal account?';

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
    const dialog = page.getByRole('dialog', { name: 'Start a run' });
    check('Start run opens one screen', await dialog.waitFor({ timeout: 30_000 }).then(() => true, () => false));

    // The picker lists what the service says it can run, less workflows that take an agent id (those start from Chat).
    const graphs = (await (await fetch(`${agents}/v1/graphs`, { headers: { 'X-Team-Id': 'team_all' } })).json()).data;
    const expected = graphs.filter((g) => g.input.every((f) => f.type !== 'agent')).map((g) => g.title);
    await dialog.getByRole('combobox', { name: 'Workflow' }).click();
    const offered = (await page.getByRole('option').allInnerTexts()).map((t) => t.split(/\n| · /)[0].trim());
    check('the picker offers the service graphs that take no agent', expected.length > 0 && JSON.stringify(offered) === JSON.stringify(expected), { offered, expected });
    await page.getByRole('option', { name: 'Product question' }).click();

    // Refusal half: an empty question is refused in the form and reaches no API.
    const posts = [];
    page.on('request', (r) => r.method() === 'POST' && r.url().startsWith(agents) && posts.push(r.url()));
    await dialog.getByTestId('start-run-submit').click();
    check('an empty question is refused before any call', (await dialog.getByText('Question is required.').count()) === 1 && posts.length === 0, posts);

    await dialog.getByLabel('Question').fill(QUESTION);
    const created = page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/threads`, { timeout: 60_000 });
    const streamed = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/threads\/[^/]+\/runs\/stream$/.test(r.url()), { timeout: 120_000 });
    await dialog.getByTestId('start-run-submit').click();
    const createRes = await created;
    const tid = (await createRes.json()).data?.threadId;
    check('the thread was created on simple_workflow (201)', createRes.status() === 201 && JSON.parse(createRes.request().postData() ?? '{}').graph === 'simple_workflow', createRes.status());
    check('the run streamed (200)', (await streamed).status() === 200);

    await page.waitForURL(`**/cases?run=${tid}`, { timeout: 60_000 });
    const trace = page.getByTestId('run-trace');
    await trace.waitFor({ timeout: 60_000 }).catch(() => undefined);
    const labels = await trace.locator('li').allInnerTexts().catch(() => []);
    const order = labels.map((l) => l.split('\n')[0]);
    check('the run sheet opens on that run with classify then answer', order.indexOf('Classify') >= 0 && order.indexOf('Classify') < order.indexOf('Answer'), labels);

    await page.keyboard.press('Escape');
    await page.getByText(/^Done today/).first().click();
    const row = page.getByTestId(`run-row-${tid}`);
    const listed = await row.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check('the run is a Cases row under Done today, subject is the question', listed && (await row.getByText(QUESTION).count()) > 0);
    check('the row says Done', listed && (await row.getByText('Done', { exact: true }).count()) > 0);

    // Non-vacuous: the browser's thread holds the answer the workflow produced, read from the service, not the page.
    const state = (await (await fetch(`${agents}/v1/threads/${tid}/state`, { headers: { 'X-Team-Id': 'team_all' } })).json()).data;
    const cites = state?.values?.citations ?? [];
    check('the thread answered with $25,000 citing doc_wire_limits', (state?.values?.answer ?? '').includes('$25,000') && cites[0]?.documentId === 'doc_wire_limits', state?.values);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
