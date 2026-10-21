// uc-123 run and review controls show only to roles that can use them, ui layer:
// docs/usecases/console/role-hidden-run-and-review-controls.md. Signed in through platform-service: Ravi, a viewer,
// sees no run button on a workflow; James, a builder, does. On James's run, Ravi sees no Cancel and James does; on
// James's publish request, Ravi sees who decides instead of Approve, and Maya, a reviewer, gets the decision form.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const TAG = Math.random().toString(36).slice(2, 6);
const WORKFLOW = `
schemaVersion: 2
id: uc123_${TAG}
name: Address check (uc-123)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}
connections:
  - {from: {node: start, port: payload}, to: {node: done, port: in}}
`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    // James's team workflow, saved through the API.
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@harborpine.example')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ yaml: WORKFLOW }) });
    if (!saved.ok) throw new Error(`setup: save workflow answered ${saved.status}: ${await saved.text()}`);
    const wid = `uc123_${TAG}`;
    // Live, so the old console offered Start run to anyone who could read it.
    const M = { Authorization: `Bearer ${await tokenFor('m.okafor@harborpine.example')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const asked = (await (await fetch(`${agents}/v1/workflows/definitions/${wid}/publish-requests`, { method: 'POST', headers: J, body: '{}' })).json()).data;
    const live = asked?.status === 'approved' ? asked : (await (await fetch(`${agents}/v1/publish-requests/${asked?.id}/decision`, { method: 'POST', headers: M, body: JSON.stringify({ decision: 'approved' }) })).json()).data;
    if (live?.status !== 'approved') throw new Error(`setup: publish ${JSON.stringify(live ?? asked).slice(0, 300)}`);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const runButton = async (email) => {
        const page = await signIn(browser, consoleUrl, email, errors);
        await page.goto(`${consoleUrl}/workflows/definitions/${wid}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.locator('.react-flow').first().waitFor({ timeout: 120_000 });
        await page.waitForTimeout(800);
        return page.getByTestId('definition-start-run').count();
      };
      const ravi = await runButton('r.menon@harborpine.example');
      const james = await runButton('j.richardson@harborpine.example');
      check('a viewer sees no run button on a workflow; a builder does', ravi === 0 && james === 1, { ravi, james, wid });

      // James's live run, queued with no worker: Cancel shows to its starter only.
      const run = (await (await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: wid, mode: 'live', input: {} }) })).json()).data;
      const cancelButton = async (email) => {
        const page = await signIn(browser, consoleUrl, email, errors);
        await page.goto(`${consoleUrl}/workflows/runs/${run.runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByText(run.runId).first().waitFor({ timeout: 120_000 }).catch(() => undefined);
        await page.waitForTimeout(1500);
        return page.getByTestId('run-cancel').count();
      };
      const raviCancel = await cancelButton('r.menon@harborpine.example');
      const jamesCancel = await cancelButton('j.richardson@harborpine.example');
      check("Cancel shows to the run's starter, not to a viewer", raviCancel === 0 && jamesCancel === 1, { raviCancel, jamesCancel, run: run?.runId });

      // James's publish request waits for a reviewer: Ravi, a viewer, sees who decides; Maya gets the form.
      const agent = (await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Desk ${TAG}`, role: 'Answers' }) })).json()).data;
      const request = (await (await fetch(`${agents}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: agent.version, note: 'uc-123' }) })).json()).data;
      const decideControls = async (email) => {
        const page = await signIn(browser, consoleUrl, email, errors);
        await page.goto(`${consoleUrl}/reviews?review=${request.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('dialog').first().waitFor({ timeout: 120_000 });
        await page.waitForTimeout(1500);
        return { approve: await page.getByRole('dialog').getByRole('button', { name: /^Approve/ }).count(), decidedBy: await page.getByTestId('review-decided-by').count() };
      };
      const raviDecide = await decideControls('r.menon@harborpine.example');
      const mayaDecide = await decideControls('m.okafor@harborpine.example');
      check('a viewer sees who decides and no Approve; a reviewer gets the decision form', request?.status === 'pending' && raviDecide.approve === 0 && raviDecide.decidedBy === 1 && mayaDecide.approve > 0 && mayaDecide.decidedBy === 0, { status: request?.status, raviDecide, mayaDecide });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, agentsEnv: { OPS_REGISTRY_AUTO_APPROVE: 'false' } },
);

finish();
