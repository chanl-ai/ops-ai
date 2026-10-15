// uc-053 the requester cannot approve a workflow's access, another person can, ui layer:
// docs/usecases/console/workflow-access-approved-by-another-person.md. Signed in through platform-service as two
// people: James requests a workflow's access to an operation, Priya approves it on the module's Access tab.
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const HOST = `statements-${TAG}.bank.example`;
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
async function signIn(browser, consoleUrl, email) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    // James's published module with one read, and his request for a workflow's access to it.
    const J = as(await tokenFor('j.richardson@northfieldbank.com'), 'team_ops');
    const N = as(await tokenFor('n.petrov@northfieldbank.com'), 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: J, body: JSON.stringify({ value: HOST, note: 'uc-053' }) });
    const id = (await (await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Statements ${TAG}`, name: `uc053-${TAG}`, type: 'http' }) })).json()).data.id;
    const op = `get_statement_${TAG}`;
    await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: op, description: '', access: 'read', method: 'GET', url: `https://${HOST}/v1/x` }) });
    const reviewed = (await (await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-053' }) })).json()).data;
    const rid = reviewed.reviews.find((r) => r.decision === 'pending').id;
    await fetch(`${tools}/v1/tool-modules/${id}/reviews/${rid}/decide`, { method: 'POST', headers: N, body: JSON.stringify({ decision: 'approved' }) });
    const workflows = (await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/workflows?pageSize=50`, { headers: J })).json()).data;
    const wf = (workflows.data ?? workflows)[0];
    const asked = await fetch(`${tools}/v1/tool-modules/${id}/approvals`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: wf.id, environment: 'test', operations: [op], expiresInDays: 30, justification: 'Statements for disputes' }) });
    const approval = (await asked.json()).data;
    if (asked.status !== 201) throw new Error(`setup: the approval request answered ${asked.status}: ${JSON.stringify(approval).slice(0, 300)}`);

    const browser = await chromium.launch();
    try {
      const errors = [];
      const row = (page) => page.getByRole('row', { name: new RegExp(wf.name) });

      const jp = await signIn(browser, consoleUrl, 'j.richardson@northfieldbank.com');
      jp.on('pageerror', (e) => errors.push(e.message));
      await jp.goto(`${consoleUrl}/tools/${id}?tab=access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await row(jp).waitFor({ timeout: 120_000 });
      const jApprove = row(jp).getByRole('button', { name: 'Approve' });
      check('the requester sees Approve switched off on his own request', (await jApprove.isDisabled()) && /You requested this/.test((await jApprove.getAttribute('title')) ?? ''));

      const pp = await signIn(browser, consoleUrl, 'p.shah@northfieldbank.com');
      pp.on('pageerror', (e) => errors.push(e.message));
      await pp.goto(`${consoleUrl}/tools/${id}?tab=access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await row(pp).waitFor({ timeout: 120_000 });
      const pApprove = row(pp).getByRole('button', { name: 'Approve' });
      check('another person in the owner team sees Approve on', !(await pApprove.isDisabled()));
      await pApprove.click();
      const decided = armed(pp.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/approvals/${approval.id}/decide`), { timeout: 60_000 }));
      await pp.getByRole('dialog').getByRole('button', { name: 'Approve' }).click();
      const res = await decided;
      check('her approval is accepted by tools-service', res?.status() === 200, res?.status());
      const after = (await (await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J })).json()).data.approvals.find((a) => a.id === approval.id);
      check('the workflow now holds an approved grant decided by her', after?.status === 'approved' && /Priya|p\.shah/.test(after?.decidedBy ?? ''), { status: after?.status, decidedBy: after?.decidedBy });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
