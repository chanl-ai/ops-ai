// uc-092 a builder designs a workflow in forms, publishes it through review, pauses, resumes and cancels a run, ui
// layer: docs/usecases/agents-service/workflow-lifecycle-and-forms.md. Platform sign-in (James builds, Maya approves),
// tools-service as the gateway so the tool form lists real operations, publish requests left pending for a second
// person, and workflow workers this script starts and stops. No model is called.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const NAME = `Refund triage 092 ${Math.random().toString(36).slice(2, 6)}`;
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;

await withUiStack(
  async (consoleUrl, stack) => {
    const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
    const H = as(await tokenFor(JAMES));
    const M = as(await tokenFor(MAYA));
    const api = async (path, init = {}, headers = H) => fetch(`${agents}${path}`, { ...init, headers });
    const types = (await (await api('/v1/workflows/node-types')).json()).data;
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // 1. New workflow: a runner draft opens in the editor.
      await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'New workflow' }).first().click({ timeout: 120_000 });
      const dialog = page.getByRole('dialog', { name: 'New workflow' });
      await dialog.getByLabel('Name').fill(NAME);
      await dialog.getByLabel('Starts when').fill('A customer asks for a refund');
      const created = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/workflows/definitions`, { timeout: 60_000 }));
      await dialog.getByRole('button', { name: 'Create and open' }).click();
      const id = (await (await created).json()).data?.workflowId;
      await page.waitForURL(`**/workflows/definitions/${id}`, { timeout: 60_000 });
      await page.getByTestId('definition-node').first().waitFor({ timeout: 60_000 });
      const stage = () => page.getByTestId('definition-stage').getAttribute('data-stage');
      check('a new workflow is saved as a draft', (await stage()) === 'draft', await stage());

      // 2. Every built step type is edited in its generated form: one control per setting, the JSON closed.
      const latest = new Map();
      for (const t of types) if (!latest.has(t.id) || latest.get(t.id).version < t.version) latest.set(t.id, t);
      const forms = [];
      for (const t of latest.values()) {
        await page.getByTestId('definition-add-step').click();
        await page.getByTestId('definition-palette-group').getByText(t.label, { exact: true }).first().click();
        const form = page.getByTestId('node-settings-form').first();
        await form.waitFor({ timeout: 10_000 });
        const fields = await form.locator(':scope > div').count();
        const jsonShown = await page.getByTestId('definition-node-parameters').isVisible();
        forms.push({ type: t.id, fields, expected: t.ui.order.length, jsonShown });
        await page.getByTestId('definition-node-delete').click();
      }
      check('each built step type opens a generated form with one control per setting and no JSON editor in view', forms.length === latest.size && forms.length > 0 && forms.every((f) => f.fields === f.expected && !f.jsonShown), forms);

      // The agent, tool and step pickers read their choices from the platform, not from typed ids.
      const agentTypes = await (await api('/v1/workflows/option-sources?source=agents')).json();
      const toolTypes = await api('/v1/workflows/option-sources?source=tools');
      await page.getByTestId('definition-add-step').click();
      await page.getByTestId('definition-palette-group').getByText(latest.get('ops.ai.agent').label, { exact: true }).first().click();
      await page.locator('[data-field$="-agent"]').first().click();
      const offered = await page.getByRole('option').allInnerTexts();
      await page.keyboard.press('Escape');
      await page.getByTestId('definition-node-delete').click();
      check('the agent field lists the published agents from the option source', agentTypes.data.length > 0 && agentTypes.data.every((a) => offered.some((o) => o.includes(a.label))) && toolTypes.status === 200, { offered, agents: agentTypes.data.map((a) => a.label), tools: toolTypes.status });

      // 3. The End step through its form: an outcome, and the output read from the run's input.
      await page.locator('[data-testid="definition-node"][data-node-id="done"]').dblclick();
      await page.locator('[data-field="node-done-outcome"]').fill('refunded');
      const output = page.locator('[data-mapping="node-done-output"]');
      await output.getByRole('combobox', { name: 'Value kind' }).click();
      await page.getByRole('option', { name: 'Step output' }).click();
      await output.getByRole('combobox', { name: 'Insert a step output' }).click();
      await page.getByRole('option', { name: /Run input/ }).click();
      await page.locator('[data-field="node-done-output"]').fill('$.input.amount');
      await page.getByTestId('definition-checks-count').getByText(/No problems/).waitFor({ timeout: 30_000 }).catch(() => undefined);
      const saved = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/workflows/definitions`, { timeout: 60_000 }));
      await page.getByTestId('definition-save').click();
      const v2 = (await (await saved).json()).data;
      const stored = (await (await api(`/v1/workflows/definitions/${id}`)).json()).data;
      const done = stored.definition.nodes.find((n) => n.id === 'done');
      await page.waitForFunction(() => document.querySelector('[data-testid="definition-stage"]')?.getAttribute('data-stage') === 'draft', null, { timeout: 30_000 }).catch(() => undefined);
      check('Save stores the form as version 2, a draft, with the outcome and a path as output', v2?.version === 2 && stored.stage === 'draft' && done?.parameters?.outcome === 'refunded' && done?.parameters?.output === '$.input.amount', { v2, stage: stored.stage, done: done?.parameters });

      // 4. Non-vacuous half: a draft starts no live run, from the API or the editor.
      const early = await api('/v1/runs', { method: 'POST', body: JSON.stringify({ workflowId: id, input: { amount: 42 } }) });
      await page.getByTestId('definition-start-run').click();
      const liveOff = await page.locator('#definition-run-live').isDisabled();
      await page.keyboard.press('Escape');
      check('a draft is refused a live run (409 not_live) and the editor offers only a test run', early.status === 409 && (await early.json()).error?.code === 'not_live' && liveOff, { status: early.status, liveOff });

      // 5. Publish through Reviews: James asks, the version is in review, and he cannot approve it himself.
      await page.getByTestId('definition-publish').click();
      await page.getByLabel(/What changed/).fill('Refunds end with the amount as the result');
      const requested = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/workflows/definitions/${id}/publish-requests`), { timeout: 60_000 }));
      await page.getByTestId('definition-publish-submit').click();
      const review = (await (await requested).json()).data;
      await page.waitForFunction(() => document.querySelector('[data-testid="definition-stage"]')?.getAttribute('data-stage') === 'in_review', null, { timeout: 30_000 }).catch(() => undefined);
      const reviewLink = await page.getByTestId('definition-review-link').getAttribute('href');
      const own = await api(`/reviews/${review?.id}/decision`, { method: 'POST', body: JSON.stringify({ decision: 'approved' }) });
      check('the request is pending in Reviews, the version shows In review, and the requester cannot approve it (403)', review?.status === 'pending' && (await stage()) === 'in_review' && reviewLink?.includes(review.id) && own.status === 403, { state: review?.status, stage: await stage(), reviewLink, own: own.status });

      await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByPlaceholder('Search workflows…').fill(NAME.toLowerCase());
      const row = page.getByRole('row').filter({ hasText: NAME }).first();
      await row.waitFor({ timeout: 60_000 }).catch(() => undefined);
      const rowText = await row.innerText().catch(() => '');
      check('the Workflows list shows it as a draft with version 2 awaiting approval', /Draft/.test(rowText) && /v2 awaiting approval/.test(rowText), rowText);

      const approved = await api(`/reviews/${review?.id}/decision`, { method: 'POST', body: JSON.stringify({ decision: 'approved' }) }, M);
      await page.goto(`${consoleUrl}/workflows/definitions/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('definition-stage').waitFor({ timeout: 60_000 });
      check('Maya approves it (200) and version 2 is live', approved.status === 200 && (await stage()) === 'live', { approved: approved.status, stage: await stage() });

      // 6. A live run reaches the End step, and its output is the run's result.
      const worker = await stack.startWorker();
      await page.getByTestId('definition-start-run').click();
      const liveChosen = await page.locator('#definition-run-live').getAttribute('data-state');
      await page.getByTestId('definition-run-input').fill(JSON.stringify({ amount: 42 }));
      await page.getByTestId('definition-start-run-submit').click();
      await page.waitForURL(/\/workflows\/runs\/[^/?]+/, { timeout: 60_000 });
      const result = page.getByTestId('run-result');
      const shown = await result.waitFor({ timeout: 90_000 }).then(() => true, () => false);
      const resultText = shown ? await result.innerText() : '';
      const outcome = shown ? await result.getAttribute('data-outcome') : null;
      const ended = await page.getByText(/Ended at Done with outcome refunded/).count();
      check('the live run ends at Done and the page shows its output, 42, as the result', liveChosen === 'checked' && shown && outcome === 'refunded' && /\b42\b/.test(resultText) && ended === 1, { liveChosen, shown, outcome, resultText });

      // 7. Pause stops live starts; resume lets them through again.
      await page.goto(`${consoleUrl}/workflows/definitions/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('definition-pause').click();
      await page.getByTestId('definition-pause-confirm').click();
      await page.waitForFunction(() => document.querySelector('[data-testid="definition-stage"]')?.getAttribute('data-stage') === 'paused', null, { timeout: 30_000 }).catch(() => undefined);
      const paused = await api('/v1/runs', { method: 'POST', body: JSON.stringify({ workflowId: id, input: { amount: 42 } }) });
      const pausedCode = (await paused.json()).error?.code;
      const stagePaused = await stage();
      await page.getByTestId('definition-resume').click();
      await page.getByTestId('definition-pause-confirm').click();
      await page.waitForFunction(() => document.querySelector('[data-testid="definition-stage"]')?.getAttribute('data-stage') === 'live', null, { timeout: 30_000 }).catch(() => undefined);
      check('paused, a live start is refused (409 workflow_paused); resumed, the version is live again', stagePaused === 'paused' && paused.status === 409 && pausedCode === 'workflow_paused' && (await stage()) === 'live', { stagePaused, status: paused.status, pausedCode, after: await stage() });

      // 8. Cancel: a queued run is cancelled from its page and a worker never runs it.
      await worker.stop();
      await page.getByTestId('definition-start-run').click();
      await page.getByTestId('definition-run-input').fill(JSON.stringify({ amount: 7 }));
      await page.getByTestId('definition-start-run-submit').click();
      await page.waitForURL(/\/workflows\/runs\/[^/?]+/, { timeout: 60_000 });
      const runId = decodeURIComponent(new URL(page.url()).pathname.split('/').pop());
      await page.getByTestId('run-cancel').click();
      await page.getByTestId('run-cancel-confirm').click();
      await page.getByTestId('run-cancelled').waitFor({ timeout: 30_000 }).catch(() => undefined);
      const after = await stack.startWorker();
      await new Promise((r) => setTimeout(r, 4_000));
      const run = (await (await api(`/v1/runs/${runId}`)).json()).data;
      await after.stop();
      const status = (await page.getByTestId('run-status').innerText()).toLowerCase();
      check('Cancel run stops a queued run: the page says cancelled and a worker started afterwards runs no step', status === 'cancelled' && run?.status === 'cancelled' && run?.steps.length === 0 && (await page.getByTestId('run-cancel').count()) === 0, { status, api: run?.status, steps: run?.steps.length });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { gateway: true }, agentsEnv: { OPS_REGISTRY_AUTO_APPROVE: 'false' } },
);

finish();
