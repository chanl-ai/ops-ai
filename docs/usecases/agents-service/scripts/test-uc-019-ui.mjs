// uc-019 create a workflow, validate, test, publish and start it, ui layer:
// docs/usecases/agents-service/workflow-draft-publish-start.md. Headless Chromium against a console whose Workflows
// and Cases call the agents service registry on the scripted model.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_all', 'Content-Type': 'application/json' };
const NAME = `Statement Requests ${Math.random().toString(36).slice(2, 6)}`;
// A wait armed before a click must not reject unhandled if the script fails first: that crash skips the harness
// cleanup and leaves the servers running.
const armed = (p) => (p.catch(() => undefined), p);
const post = (path, body) => fetch(`${agents}${path}`, { method: 'POST', headers: TEAM, body: JSON.stringify(body) });

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('button', { name: 'New workflow' }).first().click({ timeout: 120_000 });
    const dialog = page.getByRole('dialog', { name: 'New workflow' });
    await dialog.getByLabel('Name').fill(NAME);
    await dialog.getByLabel('Starts when').fill('A customer asks for a statement copy');
    await dialog.getByText('Blank', { exact: true }).click();
    const created = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/workflows`, { timeout: 60_000 }));
    await dialog.getByRole('button', { name: 'Create and open' }).click();
    const createRes = await created;
    const wf = (await createRes.json()).data;
    check('New workflow creates a draft in the registry (201)', createRes.status() === 201 && wf?.status === 'draft' && wf?.version === 0, { status: createRes.status(), state: wf?.status, version: wf?.version });
    const opened = await page.waitForURL(`**/workflows/${wf?.id}`, { timeout: 60_000 }).then(() => true, () => false);
    const editorTitle = await page.getByTestId('page-title').first().innerText({ timeout: 60_000 }).catch((e) => String(e).slice(0, 120));
    check('the editor opens on the new workflow', opened && editorTitle === NAME, { opened, url: page.url(), editorTitle, errors, toast: await page.locator('[data-sonner-toast]').allInnerTexts().catch(() => []), dialog: (await dialog.innerText().catch(() => 'closed')).slice(0, 300) });

    // Non-vacuous half: a draft has no published version, so it cannot be started.
    const early = await post('/v1/threads', { graph: wf?.id });
    check('a draft workflow cannot be started', early.status >= 400 && (await page.getByTestId('workflow-start-run').count()) === 0, early.status);

    const tested = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/workflows/${wf?.id}/test`), { timeout: 60_000 }));
    await page.getByRole('button', { name: 'Test run' }).click();
    const testRes = await tested;
    const run = (await testRes.json()).data;
    check('Test run runs the draft in the service', testRes.status() === 200 && run?.status === 'completed' && run?.visited?.length >= 2, run);

    // Non-vacuous half: a step nothing reaches makes the definition invalid, and the service refuses to publish it.
    const saved = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith(`/v1/workflows/${wf?.id}/draft`), { timeout: 60_000 }));
    await page.getByPlaceholder('Search nodes…').fill('Classify');
    await page.getByTitle('Drag onto the canvas, or click to add').filter({ hasText: 'Classify and route' }).first().click();
    await saved;
    const draft = (await (await fetch(`${agents}/v1/workflows/${wf?.id}`, { headers: TEAM })).json()).data.draft?.graph;
    const refused = await post(`/v1/workflows/${wf?.id}/publish-requests`, { graph: draft, note: 'should fail' });
    const refusal = await refused.json();
    check('an invalid definition cannot be published (422 checks_failing)', refused.status === 422 && refusal?.error?.code === 'checks_failing', { status: refused.status, code: refusal?.error?.code });
    await page.getByRole('button', { name: 'Publish…' }).click();
    const pub = page.getByRole('dialog', { name: /Request first publish/ });
    const failing = await pub.getByTestId('validation-results').getByText('Every step is reachable').waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check('validation in the publish dialog shows the unreachable step', failing);
    await page.keyboard.press('Escape');

    // Remove the stray step: select it on the canvas and delete it.
    await page.locator('.react-flow__node', { hasText: 'Classify and route' }).first().click();
    const resaved = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith(`/v1/workflows/${wf?.id}/draft`), { timeout: 60_000 }));
    await page.keyboard.press('Backspace');
    await resaved;

    await page.getByRole('button', { name: 'Publish…' }).click();
    await pub.getByTestId('validation-results').getByText(/pass on draft/).waitFor({ timeout: 60_000 });
    await pub.getByLabel('What changed').fill('First publish');
    const requested = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/workflows/${wf?.id}/publish-requests`), { timeout: 60_000 }));
    await pub.getByRole('button', { name: 'Request publish' }).click();
    const pubRes = await requested;
    const review = (await pubRes.json()).data;
    check('Request publish is approved and publishes v1 (dev auto-approve)', pubRes.status() === 201 && review?.status === 'approved', { status: pubRes.status(), state: review?.status });

    await page.reload({ waitUntil: 'networkidle' });
    const start = page.getByTestId('workflow-start-run');
    check('the published workflow offers Start run', await start.waitFor({ timeout: 60_000 }).then(() => true, () => false));
    await start.click();
    const startDialog = page.getByRole('dialog', { name: 'Start a run' });
    await startDialog.getByLabel('From').fill('customer@example.com');
    await startDialog.getByLabel('Subject').fill('Statement copy for March');
    await startDialog.getByLabel('Body').fill('Please send me a copy of my March statement.');
    const threadMade = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/threads`, { timeout: 60_000 }));
    await startDialog.getByTestId('start-run-submit').click();
    const threadRes = await threadMade;
    const tid = (await threadRes.json()).data?.threadId;
    check('Start run makes a thread on the workflow', threadRes.status() === 201 && JSON.parse(threadRes.request().postData() ?? '{}').graph === wf?.id, threadRes.status());
    const inCases = await page.waitForURL(`**/cases?run=${tid}`, { timeout: 120_000 }).then(() => true, () => false);
    check('the run opens in Cases when it stops', inCases);
    const state = (await (await fetch(`${agents}/v1/threads/${tid}/state`, { headers: TEAM })).json()).data;
    check('the run finished on the published version', state?.next?.length === 0 && state?.version === 1, { next: state?.next, version: state?.version });

    // Two routes: a branch on email.subject with a default. Without the default the service fails the branch and the
    // editor shows that on the node; set through the inspector, it publishes and routes by subject.
    const made = await post('/v1/workflows', { name: `${NAME} triage`, trigger: 'Dispute email received', template: 'blank' });
    const tri = (await made.json()).data;
    const node = (id, type, x, data) => ({ id, type, position: { x, y: 200 }, data: { icon: 'git-branch', category: 'logic', description: '', ...data } });
    const graph = {
      nodes: [node('t', 'trigger', 0, { label: 'Email received', category: 'trigger' }), node('route', 'branch', 270, { label: 'Route by subject', branches: ['Urgent', 'Other'] }), node('urgent_end', 'end', 540, { label: 'Urgent handled' }), node('other_end', 'end', 540, { label: 'Other handled' })],
      edges: [
        { id: 'e1', source: 't', target: 'route' },
        { id: 'e2', source: 'route', target: 'urgent_end', sourceHandle: 'Urgent' },
        { id: 'e3', source: 'route', target: 'other_end', sourceHandle: 'Other' },
      ],
    };
    await fetch(`${agents}/v1/workflows/${tri.id}/draft`, { method: 'PUT', headers: TEAM, body: JSON.stringify({ graph }) });
    await page.goto(`${consoleUrl}/workflows/${tri.id}`, { waitUntil: 'networkidle', timeout: 120_000 });
    await page.getByRole('button', { name: 'Publish…' }).click();
    const triPub = page.getByRole('dialog', { name: /Request first publish/ });
    await triPub.getByTestId('validation-results').getByText(/default route/).first().waitFor({ timeout: 60_000 }).catch(() => undefined);
    await page.keyboard.press('Escape');
    const onNode = page.locator('.react-flow__node', { hasText: 'Route by subject' }).getByTestId('node-error');
    check('a branch with no default fails, and the error shows on the node', (await onNode.count()) === 1 && /default route/.test(await onNode.innerText()), await onNode.allInnerTexts());

    await page.locator('.react-flow__node', { hasText: 'Route by subject' }).first().click();
    const routes = page.getByTestId('routes-editor');
    await routes.getByRole('combobox', { name: 'Default route' }).click();
    await page.getByRole('option', { name: 'Other', exact: true }).click();
    await routes.getByRole('combobox', { name: 'Urgent field' }).click();
    await page.getByRole('option', { name: 'email.subject', exact: true }).click();
    const routeSaved = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith(`/v1/workflows/${tri.id}/draft`), { timeout: 60_000 }));
    await routes.getByLabel('Urgent value').fill('Urgent dispute');
    await routes.getByLabel('Urgent value').press('Enter');
    await routeSaved;
    const stored = (await (await fetch(`${agents}/v1/workflows/${tri.id}`, { headers: TEAM })).json()).data.draft?.graph?.nodes.find((n) => n.id === 'route')?.data;
    check('the inspector stores the route and the default on the node', stored?.defaultRoute === 'Other' && stored?.routes?.Urgent?.field === 'email.subject' && stored?.routes?.Urgent?.op === 'eq' && stored?.routes?.Urgent?.value === 'Urgent dispute', stored);

    await page.getByRole('button', { name: 'Publish…' }).click();
    await triPub.getByTestId('validation-results').getByText(/pass on draft/).waitFor({ timeout: 60_000 });
    check('with the default set the routes validate and the node error clears', (await onNode.count()) === 0);
    await triPub.getByLabel('What changed').fill('Two routes');
    const triReq = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/workflows/${tri.id}/publish-requests`), { timeout: 60_000 }));
    await triPub.getByRole('button', { name: 'Request publish' }).click();
    check('the two-route workflow publishes', (await triReq)?.status() === 201);
    const runOn = async (subject) => {
      const t = (await (await post('/v1/threads', { graph: tri.id })).json()).data.threadId;
      await (await post(`/v1/threads/${t}/runs/stream`, { input: { email: { sender: 'c@example.com', subject, body: 'Charged twice.', attachments: [] } } })).text();
      return (await (await fetch(`${agents}/v1/threads/${t}/runs`, { headers: TEAM })).json()).data.flatMap((r) => r.nodes ?? r.nodeSequence ?? []);
    };
    const urgent = await runOn('Urgent dispute');
    const other = await runOn('Question about a fee');
    check('a matching subject takes the Urgent route, any other the default', urgent.includes('urgent_end') && !urgent.includes('other_end') && other.includes('other_end') && !other.includes('urgent_end'), { urgent, other });
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

// The reject half: two people signed in through platform-service, publish requests left pending. James (builder)
// requests a publish and cannot approve it; Maya (approver) returns it with a reason, and nothing is published.
const platformUrl = `http://127.0.0.1:${PLATFORM_PORT}`;
const tokenFor = async (email) => (await (await fetch(`${platformUrl}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
async function signIn(browser, consoleUrl, email) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const errors = [];
      const james = await signIn(browser, consoleUrl, 'j.richardson@northfieldbank.com');
      james.on('pageerror', (e) => errors.push(e.message));
      const jamesToken = await tokenFor('j.richardson@northfieldbank.com');
      const made = await fetch(`${agents}/v1/workflows`, { method: 'POST', headers: as(jamesToken), body: JSON.stringify({ name: `${NAME} returned`, trigger: 'A customer asks for a statement copy', template: 'blank' }) });
      const wf = (await made.json()).data;

      await james.goto(`${consoleUrl}/workflows/${wf?.id}`, { waitUntil: 'networkidle', timeout: 120_000 });
      await james.getByRole('button', { name: 'Publish…' }).click();
      const pub = james.getByRole('dialog', { name: /Request first publish/ });
      await pub.getByTestId('validation-results').getByText(/pass on draft/).waitFor({ timeout: 60_000 });
      await pub.getByLabel('What changed').fill('First publish, for review');
      const requested = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/workflows/${wf?.id}/publish-requests`), { timeout: 60_000 }));
      await pub.getByRole('button', { name: 'Request publish' }).click();
      const reqRes = await requested;
      const review = reqRes ? (await reqRes.json()).data : undefined;
      check('with auto-approve off, James’s request stays pending', made.status === 201 && reqRes?.status() === 201 && review?.status === 'pending', { made: made.status, status: reqRes?.status(), state: review?.status });

      await james.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const jamesRow = james.getByTestId(`review-row-${review?.id}`);
      await jamesRow.waitFor({ timeout: 60_000 });
      await jamesRow.click();
      const jamesForm = james.getByTestId('review-decision-form');
      await jamesForm.waitFor({ timeout: 30_000 });
      // For the requester the approve button names who decides and is off.
      const ownButton = jamesForm.getByRole('button', { name: 'Another publisher approves' });
      const approveOff = (await ownButton.count()) === 1 && (await ownButton.isDisabled());
      const ownDecision = await fetch(`${agents}/reviews/${review?.id}/decision`, { method: 'POST', headers: as(jamesToken), body: JSON.stringify({ decision: 'approved' }) });
      check('the requester cannot approve his own request: the button is off and the service refuses (403)', approveOff && ownDecision.status === 403, { approveOff, status: ownDecision.status });

      const maya = await signIn(browser, consoleUrl, 'm.okafor@northfieldbank.com');
      maya.on('pageerror', (e) => errors.push(e.message));
      await maya.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const mayaRow = maya.getByTestId(`review-row-${review?.id}`);
      await mayaRow.waitFor({ timeout: 60_000 });
      await mayaRow.click();
      const form = maya.getByTestId('review-decision-form');
      await form.waitFor({ timeout: 30_000 });
      let posted = 0;
      maya.on('request', (r) => r.method() === 'POST' && r.url().endsWith(`/reviews/${review?.id}/decision`) && posted++);
      await form.getByRole('button', { name: 'Return to requester' }).click();
      const asked = await form.getByText(/Add a reason before rejecting or returning/).waitFor({ timeout: 10_000 }).then(() => true, () => false);
      check('returning without a reason is stopped in the form and sends nothing', asked && posted === 0, { asked, posted });
      await form.getByLabel(/^Reason/).fill('The trigger needs the statement month before this can go live.');
      const decided = armed(maya.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/reviews/${review?.id}/decision`), { timeout: 60_000 }));
      await form.getByRole('button', { name: 'Return to requester' }).click();
      const decision = await decided;
      check('Maya returns it with her reason (200)', decision?.status() === 200 && JSON.parse(decision.request().postData() ?? '{}').decision === 'returned', decision?.status());

      const after = (await (await fetch(`${agents}/v1/workflows/${wf?.id}`, { headers: as(await tokenFor('m.okafor@northfieldbank.com')) })).json()).data;
      check('the returned workflow is still unpublished', after?.version === 0 && after?.status === 'draft', { version: after?.version, state: after?.status });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, agentsEnv: { OPS_REGISTRY_AUTO_APPROVE: 'false' } },
);

finish();
