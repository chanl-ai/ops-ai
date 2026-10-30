// uc-049 a write runs only after as many people as its policy names approve it, ui layer:
// docs/usecases/agents-service/write-approval-policy.md. A bank write whose policy needs two approvers is granted to a
// new agent. James's chat drafts it; Maya approves in Human Tasks and the write waits for a second person; Maya cannot
// count twice; Priya approves and the write runs once. Platform sign-in, the fake bank on https, the scripted model.
import { AGENTS_PORT, TOOLS_PORT, approveToolReview, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, PRIYA, as, until } from '../../lib/workflow_ui.mjs';

const SAM = 's.adeyemi@harborpine.example';
const NADIA = 'n.petrov@harborpine.example';
const RUN = Math.random().toString(36).slice(2, 7);
const WRITE = `freeze_account_${RUN}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const call = async (method, url, headers, body) => {
  const r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};

/** Approves the open held write on the decision form as the signed-in person, confirming with the password. */
async function approve(page) {
  const form = page.getByTestId('review-decision-form');
  await form.waitFor({ timeout: 60_000 });
  // The button counts the approvals so far ("Approve · 1 of 2").
  const button = form.getByRole('button', { name: /^Approve/ });
  if (!(await button.isEnabled().catch(() => false))) return { status: 0, said: (await form.innerText()).replace(/\s+/g, ' ') };
  const sent = page.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 90_000 }).catch(() => undefined);
  await button.click();
  const reauth = page.getByRole('dialog').filter({ hasText: /Confirm it|password/i });
  if (await reauth.waitFor({ timeout: 10_000 }).then(() => true, () => false)) {
    await reauth.getByLabel(/password/i).first().fill(PASSWORD);
    await reauth.getByRole('button', { name: /confirm|sign in|continue/i }).last().click();
  }
  const res = await sent;
  return { status: res?.status() ?? 0, said: (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ') };
}

await withUiStack(
  async (consoleUrl, stack) => {
    const S = await as(SAM, 'team_security');
    await call('POST', `${tools}/v1/egress/hosts`, S, { value: stack.bank.host, note: 'uc-049' });
    await call('POST', `${tools}/v1/egress/ranges`, S, { value: stack.bank.range, note: 'uc-049' });
    // A module with one write whose policy needs two approvers, reviewed by Security and published.
    const J = await as(JAMES);
    const made = await call('POST', `${tools}/v1/tool-modules/blank`, J, { displayName: `Accounts ${RUN}`, name: `accounts-${RUN}`, type: 'http' });
    const moduleId = made.data?.id;
    const added = await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: WRITE, description: 'Freeze an account', access: 'write', method: 'POST', url: `https://${stack.bank.host}/v1/accounts/{accountId}/holds` });
    const opId = added.data?.operations?.find((o) => o.name === WRITE)?.id;
    await call('PATCH', `${tools}/v1/tool-modules/${moduleId}/operations/${opId}`, J, { approvers: 2 });
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/reviews`, J, { note: 'uc-049' });
    await approveToolReview(moduleId, await as(NADIA, 'team_security'), J);
    // agents-service reads the tool directory through a 30-second cache; the grant names the write once it is offered.
    await until(async () => ((await call('GET', `${agents}/v1/tools/options?search=${WRITE}`, J)).data?.data ?? []).some((o) => o.id === WRITE), 60);
    const agent = (await call('POST', `${agents}/v1/agents`, J, { name: `Freezer ${RUN}`, role: 'Freezes accounts' })).data;
    const granted = (await call('PATCH', `${agents}/v1/agents/${agent.id}`, J, { toolIds: [WRITE] })).data;
    await call('POST', `${agents}/v1/agents/${agent.id}/publish-requests`, J, { version: granted.version, note: 'uc-049' });
    const ran = async () => ((await call('GET', `${tools}/v1/executions?tool=${WRITE}`, J)).data?.data ?? []).filter((r) => r.status === 'ok');

    const browser = await chromium.launch();
    const errors = [];
    try {
      const james = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await james.goto(`${consoleUrl}/chat?agent=${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = james.getByRole('textbox', { name: /Message|Ask/ }).first();
      await box.waitFor({ timeout: 60_000 });
      await box.fill(`call ${WRITE} ${JSON.stringify({ accountId: 'CHQ-2219' })}`);
      const sent = james.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }).catch(() => undefined);
      await james.locator('button[aria-label="Send"]').first().click();
      await sent;
      await james.waitForURL(/\/chat\/[^/?#]+$/, { timeout: 60_000 }).catch(() => undefined);
      const thread = /\/chat\/([^/?#]+)/.exec(james.url())?.[1];
      const waiting = await james.getByTestId('approval-waiting-on').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('2 the chat drafts the write and it waits for approval', waiting && (await ran()).length === 0, { waiting, thread });

      const maya = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      await maya.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(thread ?? '')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const first = await approve(maya);
      check('3 Maya approves in Human Tasks; the write waits for a second person and nothing has run', first.status === 200 && (await ran()).length === 0 && /second|1 of 2|another/i.test(first.said), { status: first.status, said: first.said.slice(0, 300) });

      await maya.reload({ waitUntil: 'domcontentloaded' });
      const again = await approve(maya);
      check('4 Maya cannot approve it a second time, and still nothing has run', first.status === 200 && again.status !== 200 && (await ran()).length === 0, { status: again.status, said: again.said.slice(0, 300) });

      const priya = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      await priya.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(thread ?? '')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const second = await approve(priya);
      const rows = await until(async () => {
        const r = await ran();
        return r.length ? r : undefined;
      }, 60);
      check('5 Priya approves as the second person, and the write runs once', second.status === 200 && rows?.length === 1, { status: second.status, runs: rows?.length });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true, gateway: true } },
);

finish();
