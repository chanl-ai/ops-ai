// uc-099 a viewer sees the team's records read-only, ui layer: docs/usecases/console/viewer-sees-read-only-pages.md.
// Signed in through platform-service as Ravi (viewer on team_ops) and, as the control, James (builder on team_ops).
// The console reads what can() grants each person from GET /v1/me/permissions (c-186) and shows create, edit, publish,
// pause and delete only to someone it lets edit the team's records.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const RAVI = 'r.menon@harborpine.example';
const JAMES = 'j.richardson@harborpine.example';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

async function signIn(browser, consoleUrl, email, errors, mes) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  page.on('response', (r) => r.url().endsWith('/v1/me/permissions') && mes.push(`${email} ${r.status()}`));
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

    const browser = await chromium.launch();
    const errors = [];
    const mes = [];
    try {
      const ravi = await signIn(browser, consoleUrl, RAVI, errors, mes);
      const raviCreates = await creates(ravi, consoleUrl);
      check('a viewer sees no create button on agents, workflows, skills, guardrails, widgets, tools or knowledge', Object.values(raviCreates).every((v) => v === false), raviCreates);

      await ravi.goto(`${consoleUrl}/agents/${agentId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const notice = await ravi.getByTestId('read-only-notice').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const raviAgent = { notice, save: await ravi.getByTestId('agent-save-status').count(), more: await ravi.getByRole('button', { name: 'More actions' }).count(), nameDisabled: await ravi.locator('#ag-name').isDisabled().catch(() => null) };
      // The notice says why: which role changes agents here and who holds it (GET /v1/access/holders, c-186).
      const why = await ravi.getByTestId('read-only-why').filter({ hasText: 'ask' }).first().textContent({ timeout: 30_000 }).catch(() => '');
      check('the View only notice names the role that edits agents and who on the team holds it', /Builder/.test(why ?? '') && /James Richardson/.test(why ?? ''), why);
      check('a viewer opens an agent read-only: a View only notice, no save or actions, the fields disabled', raviAgent.notice && raviAgent.save === 0 && raviAgent.more === 0 && raviAgent.nameDisabled === true, raviAgent);

      // A workflow page reads the record's own canEdit, canDelete and canPublish (GET /v1/workflows/<id>).
      await ravi.goto(`${consoleUrl}/workflows/dispute_email`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const wfNotice = await ravi.getByTestId('read-only-notice').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const raviWorkflow = { notice: wfNotice, publish: await ravi.getByRole('button', { name: 'Publish…' }).count(), more: await ravi.getByRole('button', { name: 'More actions' }).count() };
      check('a viewer opens a workflow read-only: a View only notice, no Publish or actions', raviWorkflow.notice && raviWorkflow.publish === 0 && raviWorkflow.more === 0, raviWorkflow);

      // The control: a builder on the same team sees every create button and can edit the agent.
      const james = await signIn(browser, consoleUrl, JAMES, errors, mes);
      const jamesCreates = await creates(james, consoleUrl);
      await james.goto(`${consoleUrl}/agents/${agentId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('agent-save-status').waitFor({ timeout: 60_000 }).catch(() => undefined);
      const jamesAgent = { save: await james.getByTestId('agent-save-status').count(), notice: await james.getByTestId('read-only-notice').count(), nameDisabled: await james.locator('#ag-name').isDisabled().catch(() => null) };
      check('a builder on the same team sees every create button and edits the agent', Object.values(jamesCreates).every(Boolean) && jamesAgent.save === 1 && jamesAgent.notice === 0 && jamesAgent.nameDisabled === false, { jamesCreates, jamesAgent });

      await james.goto(`${consoleUrl}/workflows/dispute_email`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByRole('button', { name: 'More actions' }).waitFor({ timeout: 60_000 }).catch(() => undefined);
      const jamesWorkflow = { notice: await james.getByTestId('read-only-notice').count(), more: await james.getByRole('button', { name: 'More actions' }).count() };
      check('a builder opens the same workflow with its actions and no View only notice', jamesWorkflow.notice === 0 && jamesWorkflow.more === 1, jamesWorkflow);

      check('what each person may do is read from GET /v1/me/permissions', mes.some((m) => m.startsWith(`${RAVI} 200`)) && mes.some((m) => m.startsWith(`${JAMES} 200`)), mes);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
