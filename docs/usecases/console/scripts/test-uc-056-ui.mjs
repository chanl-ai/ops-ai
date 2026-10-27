// uc-056 a grant whose operation is no longer offered shows as stale and can be removed, ui layer:
// docs/usecases/console/stale-grants-removed.md. Signed in through platform-service; agents-service reads the tool
// catalogue from this run's tools-service.
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const HOST = `statements-${TAG}.bank.example`;
const OP = `get_statement_${TAG}`;
const KEPT = `get_balance_${TAG}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor('j.richardson@harborpine.example'), 'team_ops');
    const N = as(await tokenFor('n.petrov@harborpine.example'), 'team_security');
    const S = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
    // Two published modules with one read each, both granted to a new agent; one module will go away.
    // Egress writes are Security-admin only, so the host is added as Sam.
    await json(await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: HOST, note: 'uc-056' }) }));
    const publish = async (name, op) => {
      const id = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: name, name: `uc056-${op}`.replaceAll('_', '-'), type: 'http' }) }))).id;
      await json(await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: op, description: name, access: 'read', method: 'GET', url: `https://${HOST}/v1/x` }) }));
      await json(await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-056' }) }));
      await approveToolReview(id, N, J);
      return id;
    };
    const mid = await publish(`Statements ${TAG}`, OP);
    await publish(`Balances ${TAG}`, KEPT);
    await new Promise((r) => setTimeout(r, 31_000)); // agents-service keeps each tenant's tool list for 30 seconds
    const catalogue = await json(await fetch(`${agentsUrl}/v1/tools`, { headers: J }));
    const tool = catalogue.find((t) => t.name === OP);
    const kept = catalogue.find((t) => t.name === KEPT);
    if (!tool || !kept) throw new Error(`setup: ${OP} or ${KEPT} is not in agents-service's catalogue (${catalogue.length} tools)`);
    const created = await json(await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Statements desk ${TAG}`, role: 'Reads statements' }) }));
    const granted = await fetch(`${agentsUrl}/v1/agents/${created.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ toolIds: [tool.id, kept.id] }) });
    if (!granted.ok) throw new Error(`setup: granting answered ${granted.status}: ${await granted.text()}`);
    const agent = await json(granted);
    // The module goes away, so its operation is no longer offered.
    const removed = await fetch(`${tools}/v1/tool-modules/${mid}`, { method: 'DELETE', headers: J });
    // agents-service drops the module from its cached catalogue within about 30 seconds.
    let before = await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}`, { headers: J }));
    for (let i = 0; i < 20 && !before.staleToolIds.includes(tool.id); i++) {
      await new Promise((r) => setTimeout(r, 5_000));
      before = await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}`, { headers: J }));
    }
    check('agents-service reports the grant as stale once its module is deleted', removed.status === 204 && before.staleToolIds.includes(tool.id), { removed: removed.status, stale: before.staleToolIds });

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // Grants no longer offered are listed under the tools picker (c-135), each with Remove.
      const stale = page.getByTestId('stale-grants');
      const shown = await stale.waitFor({ timeout: 120_000 }).then(() => true, () => false);
      check('the tools section lists the grant under "No longer offered"', shown && (await stale.getByText(tool.id).count()) === 1);
      // The removal saves itself into the draft a second later (c-172), so the wait is armed before it.
      const patched = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/agents/${agent.id}`), { timeout: 60_000 });
      await stale.getByRole('button', { name: `Remove ${tool.id}` }).click();
      check('Remove takes it off the list', (await page.getByTestId('stale-grants').count()) === 0);
      const res = await patched;
      const after = await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}`, { headers: J }));
      check('saving drops the removed grant, keeps the one still offered, and leaves nothing stale', res.status() === 200 && JSON.stringify(after.toolIds) === JSON.stringify([kept.id]) && after.staleToolIds.length === 0, { status: res.status(), stale: after.staleToolIds, after: after.toolIds });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { gateway: true } },
);

finish();
