// uc-099 a viewer sees the team's records read-only, ui layer: docs/usecases/console/viewer-sees-read-only-pages.md.
// Signed in through platform-service as Ravi (viewer on team_ops) and, as the control, James (builder on team_ops).
// The console reads what can() grants each person from the `permissions` field of GET /v1/me and shows create, edit, publish,
// pause and delete only to someone it lets edit the team's records.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const RAVI = 'r.menon@harborpine.example';
const WORKFLOW_ID = 'uc099ui_read_only';
const WORKFLOW = `
schemaVersion: 2
id: ${WORKFLOW_ID}
name: Read-only check (uc-099 ui)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: fields, type: ops.data.set, typeVersion: 1, name: Set fields, parameters: {values: {customer: "$.input.customerId"}}}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}
connections:
  - {from: {node: start, port: payload}, to: {node: fields, port: in}}
  - {from: {node: fields, port: out}, to: {node: done, port: in}}
`;
const JAMES = 'j.richardson@harborpine.example';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

async function signIn(browser, consoleUrl, email, errors, mes) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  page.on('response', (r) => /\/v1\/me(\?|$)/.test(r.url()) && r.json().then((b) => b?.data?.permissions && mes.push(`${email} ${r.status()}`), () => undefined));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

// What a person sees on each builder list page: the create button, by test id or name.
const CREATE = [
  ['/agents', (p) => p.getByTestId('create-agent-button'), 'Agents'],
  ['/workflows', (p) => p.getByRole('button', { name: 'New workflow' }), 'Workflows'],
  ['/skills', (p) => p.getByTestId('generate-skill-button'), 'Skills'],
  ['/guardrails', (p) => p.getByTestId('new-guardrail-button'), 'Guardrails'],
  ['/widgets', (p) => p.getByTestId('new-widget-button'), 'Widgets'],
  ['/tools', (p) => p.getByTestId('new-module'), 'Tools'],
  ['/knowledge', (p) => p.getByRole('button', { name: 'New knowledge base' }), 'Knowledge bases'],
];

async function creates(page, consoleUrl) {
  const seen = {};
  for (const [path, button, title] of CREATE) {
    await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByTestId('page-title').filter({ hasText: title }).first().waitFor({ timeout: 120_000 });
    // The role arrives after the page shell; give it time to show the button before counting it absent.
    seen[path] = await button(page).first().waitFor({ timeout: 15_000 }).then(() => true, () => false);
  }
  return seen;
}

await withUiStack(
  async (consoleUrl) => {
    const agents = (await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/agents?pageSize=5`, { headers: { Authorization: `Bearer ${await tokenFor(RAVI)}`, 'X-Team-Id': 'team_ops' } })).json()).data;
    const agentId = (agents.data ?? agents)[0]?.id;
    if (!agentId) throw new Error('setup: the viewer lists no agent');
    // A workflow the runner holds, made by the builder: the old engine's workflows no longer open in the console.
    const made = await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/workflows/definitions`, { method: 'POST', headers: { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' }, body: JSON.stringify({ yaml: WORKFLOW }) });
    if (made.status !== 201) throw new Error(`setup: the workflow answered ${made.status}: ${await made.text()}`);

    const browser = await chromium.launch();
    const errors = [];
    const mes = [];
    try {
      const ravi = await signIn(browser, consoleUrl, RAVI, errors, mes);
      const raviCreates = await creates(ravi, consoleUrl);
      check('a viewer sees no create button on agents, workflows, skills, guardrails, widgets, tools or knowledge', Object.values(raviCreates).every((v) => v === false), raviCreates);

      await ravi.goto(`${consoleUrl}/agents/${agentId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const notice = await ravi.getByTestId('read-only-notice').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const raviAgent = { notice, save: await ravi.getByTestId('save-state').count(), more: await ravi.getByRole('button', { name: 'More actions' }).count(), nameInput: await ravi.getByTestId('page-title-input').count() };
      // The notice says why: which role changes agents here and who holds it (GET /v1/access/holders).
      const why = await ravi.getByTestId('read-only-why').filter({ hasText: 'ask' }).first().textContent({ timeout: 30_000 }).catch(() => '');
      check('the View only notice names the role that edits agents and who on the team holds it', /Builder/.test(why ?? '') && /James Richardson/.test(why ?? ''), why);
      check('a viewer opens an agent read-only: a View only notice, no save or actions, the name not editable', raviAgent.notice && raviAgent.save === 0 && raviAgent.more === 0 && raviAgent.nameInput === 0, raviAgent);

      // A workflow page reads the record's own canEdit, canDelete and canPublish (GET /v1/workflows/<id>).
      await ravi.goto(`${consoleUrl}/workflows/definitions/${WORKFLOW_ID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const wfNotice = await ravi.getByTestId('definition-view-only').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const raviWorkflow = { notice: wfNotice, save: await ravi.getByTestId('definition-save').count(), lifecycle: await ravi.getByTestId('definition-lifecycle').count() };
      check('a viewer opens a workflow read-only: a View only line, no Save or publish actions', raviWorkflow.notice && raviWorkflow.save === 0 && raviWorkflow.lifecycle === 0, raviWorkflow);

      // The control: a builder on the same team sees every create button and can edit the agent.
      const james = await signIn(browser, consoleUrl, JAMES, errors, mes);
      const jamesCreates = await creates(james, consoleUrl);
      await james.goto(`${consoleUrl}/agents/${agentId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('save-state').waitFor({ timeout: 60_000 }).catch(() => undefined);
      const jamesAgent = { save: await james.getByTestId('save-state').count(), notice: await james.getByTestId('read-only-notice').count(), nameInput: await james.getByTestId('page-title-input').isEnabled().catch(() => null) };
      check('a builder on the same team sees every create button and edits the agent', Object.values(jamesCreates).every(Boolean) && jamesAgent.save === 1 && jamesAgent.notice === 0 && jamesAgent.nameInput === true, { jamesCreates, jamesAgent });

      await james.goto(`${consoleUrl}/workflows/definitions/${WORKFLOW_ID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('definition-lifecycle').waitFor({ timeout: 60_000 }).catch(() => undefined);
      const jamesWorkflow = { notice: await james.getByTestId('definition-view-only').count(), save: await james.getByTestId('definition-save').count(), lifecycle: await james.getByTestId('definition-lifecycle').count() };
      check('a builder opens the same workflow with Save and its publish actions and no View only line', jamesWorkflow.notice === 0 && jamesWorkflow.save === 1 && jamesWorkflow.lifecycle === 1, jamesWorkflow);

      check('what each person may do is read from the permissions GET /v1/me returns', mes.some((m) => m.startsWith(`${RAVI} 200`)) && mes.some((m) => m.startsWith(`${JAMES} 200`)), mes);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
