// uc-053 a workflow's access is decided in Human Tasks by another person, ui layer:
// docs/usecases/console/workflow-access-approved-by-another-person.md. Signed in through platform-service as two
// people: James requests a workflow's access to an operation, Priya follows the Access tab's link and approves it in
// Human Tasks, where the request waits as its system workflow run (c-166, c-257).
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

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
  async (consoleUrl, stack) => {
    // The request's system workflow runs on a worker that calls the tools gateway (c-257).
    await stack.startWorker();
    // James's published module with one read, and his request for a workflow's access to it.
    const J = as(await tokenFor('j.richardson@northfieldbank.com'), 'team_ops');
    const N = as(await tokenFor('n.petrov@northfieldbank.com'), 'team_security');
    // Only a Security admin changes the egress allow-list (c-079), so Sam lists the host.
    const S = as(await tokenFor('s.adeyemi@northfieldbank.com'), 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: HOST, note: 'uc-053' }) });
    const id = (await (await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Statements ${TAG}`, name: `uc053-${TAG}`, type: 'http' }) })).json()).data.id;
    const op = `get_statement_${TAG}`;
    await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: op, description: '', access: 'read', method: 'GET', url: `https://${HOST}/v1/x` }) });
    const reviewed = (await (await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-053' }) })).json()).data;
    await approveToolReview(id, N);
    const workflows = (await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/workflows?pageSize=50`, { headers: J })).json()).data;
    const wf = (workflows.data ?? workflows)[0];
    const asked = await fetch(`${tools}/v1/tool-modules/${id}/approvals`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: wf.id, environment: 'test', operations: [op], expiresInDays: 30, justification: 'Statements for disputes' }) });
    const approval = (await asked.json()).data;
    if (asked.status !== 201) throw new Error(`setup: the approval request answered ${asked.status}: ${JSON.stringify(approval).slice(0, 300)}`);

    const browser = await chromium.launch();
    try {
      const errors = [];
      const row = (page) => page.getByRole('row', { name: new RegExp(wf.name) });

      // c-257: the request runs as the tool_access_request system workflow; the module's Access tab links to the run's
      // review by its run key and decides nothing itself.
      check('1 the request names its workflow run', approval.reviewId === `tool_access.requested:${approval.id}`, approval);
      const P = as(await tokenFor('p.shah@northfieldbank.com'), 'team_ops');
      const byKey = `http://127.0.0.1:${AGENTS_PORT}/reviews/by-run-key/${encodeURIComponent(approval.reviewId)}`;
      let waiting = null;
      for (let i = 0; i < 120 && !waiting; i++) {
        const r = await fetch(byKey, { headers: P });
        if (r.status === 200) waiting = (await r.json()).data;
        else await new Promise((done) => setTimeout(done, 500));
      }
      check('1 its run waits in Human Tasks for the module team', waiting?.status === 'pending' && waiting?.policy?.reviewers === 'team_ops', waiting && { status: waiting.status, policy: waiting.policy });
      const jp = await signIn(browser, consoleUrl, 'j.richardson@northfieldbank.com');
      jp.on('pageerror', (e) => errors.push(e.message));
      await jp.goto(`${consoleUrl}/tools/${id}?tab=access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await row(jp).waitFor({ timeout: 120_000 });
      const link = row(jp).getByRole('link', { name: 'Decide in Human Tasks' });
      check('2 the Access tab links the request to Human Tasks and offers no Approve', (await link.getAttribute('href')) === `/reviews?runKey=${encodeURIComponent(approval.reviewId)}` && (await row(jp).getByRole('button', { name: 'Approve' }).count()) === 0);

      const pp = await signIn(browser, consoleUrl, 'p.shah@northfieldbank.com');
      pp.on('pageerror', (e) => errors.push(e.message));
      await pp.goto(`${consoleUrl}/tools/${id}?tab=access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await row(pp).getByRole('link', { name: 'Decide in Human Tasks' }).click();
      const sheet = pp.getByTestId('review-sheet');
      await sheet.waitFor({ state: 'visible', timeout: 60_000 });
      check('3 Human Tasks opens the request for another person in the owner team', (await sheet.innerText()).includes(`Let ${wf.name} use Statements ${TAG}?`));
      const decided = armed(pp.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/decision'), { timeout: 60_000 }));
      // A workflow step decides by its options; Approve authorises the run's grant (Reject asks for a reason).
      await pp.getByTestId('option-decision-form').getByTestId('decide-approve').click();
      const res = await decided;
      check('4 her approval is accepted', res?.status() === 200, res?.status());
      // The run's apply step grants it through the gateway once the worker resumes the run.
      let after = null;
      for (let i = 0; i < 120 && after?.status !== 'approved'; i++) {
        after = (await (await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J })).json()).data.approvals.find((a) => a.id === approval.id);
        if (after?.status !== 'approved') await new Promise((done) => setTimeout(done, 500));
      }
      check('4 the workflow now holds an approved grant decided by her', after?.status === 'approved' && /Priya|p\.shah/.test(after?.decidedBy ?? ''), { status: after?.status, decidedBy: after?.decidedBy });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { gateway: true } },
);

finish();
