// uc-143 Access › Tool access lists every workflow's tool access, ui layer: docs/usecases/console/tool-access.md
// (c-144). James asks for a workflow's access to his published module through the API; the console then lists it.
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
  async (consoleUrl) => {
    // James's published module with one read, and his request for a workflow's access to it.
    const J = as(await tokenFor('j.richardson@northfieldbank.com'), 'team_ops');
    const N = as(await tokenFor('n.petrov@northfieldbank.com'), 'team_security');
    // Only a Security admin changes the egress allow-list (c-079), so Sam lists the host.
    const S = as(await tokenFor('s.adeyemi@northfieldbank.com'), 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: HOST, note: 'uc-143' }) });
    const id = (await (await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Statements ${TAG}`, name: `uc143-${TAG}`, type: 'http' }) })).json()).data.id;
    const op = `get_statement_${TAG}`;
    await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: op, description: '', access: 'read', method: 'GET', url: `https://${HOST}/v1/x` }) });
    const reviewed = (await (await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-143' }) })).json()).data;
    await approveToolReview(id, N);
    const workflows = (await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/workflows?pageSize=50`, { headers: J })).json()).data;
    const wf = (workflows.data ?? workflows)[0];
    const asked = await fetch(`${tools}/v1/tool-modules/${id}/approvals`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: wf.id, environment: 'test', operations: [op], expiresInDays: 30, justification: 'Statements for disputes' }) });
    const approval = (await asked.json()).data;
    if (asked.status !== 201) throw new Error(`setup: the approval request answered ${asked.status}`);
    const counts = (await (await fetch(`${tools}/v1/tool-modules/grants?view=all`, { headers: J })).json()).data.facets.view;

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await signIn(browser, consoleUrl, 'j.richardson@northfieldbank.com');
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));

      // 1. Access has a Tool access page, reached from the title's page menu, and each view's count is the server's.
      await page.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('title-switcher').click();
      await page.getByTestId('title-switcher-access-tool-access').click();
      await page.waitForURL('**/access/tool-access');
      const tabs = page.getByRole('tablist', { name: 'Tool access views' });
      await tabs.waitFor();
      const shown = Object.fromEntries((await tabs.getByRole('tab').allInnerTexts()).map((t) => { const [label, n] = t.split(' · '); return [label.trim(), Number(n)]; }));
      check('1 Access › Tool access shows each view with the server’s count', shown.Requested === counts.requested && shown.All === counts.all && counts.requested >= 1, { shown, counts });

      // 2. The Requested view asks the server for that view and lists the request with its workflow and module.
      const asked2 = page.waitForRequest((r) => r.url().includes('/v1/tool-modules/grants?') && r.url().includes('view=requested'));
      await tabs.getByRole('tab', { name: /^Requested/ }).click();
      const sent = await asked2.then(() => true, () => false);
      const row = page.getByTestId(`grant-row-${approval.id}`);
      const listed = await row.waitFor().then(() => true, () => false);
      const text = listed ? await row.innerText() : '';
      check('2 the Requested view comes from the server and lists the request with its workflow and module', sent && listed && text.includes(wf.name) && text.includes(`Statements ${TAG}`), { sent, text: text.slice(0, 200) });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
