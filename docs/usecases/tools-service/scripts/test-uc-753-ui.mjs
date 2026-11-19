// uc-753, ui layer: docs/usecases/tools-service/an-agent-reads-with-a-tool.md. James chats with an agent that holds a read
// and a write on the mock bank: the read answers in the chat at once, the write stops on a waiting-for-approval card and
// the tool-call log is empty of it; Maya approves in Human Tasks and the write runs once. Platform sign-in, the fake
// bank on https, the scripted model.
import { AGENTS_PORT, TOOLS_PORT, approveToolReview, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, as, until, writeApprovalsOn } from '../../lib/workflow_ui.mjs';

const NADIA = 'n.petrov@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const RUN = Math.random().toString(36).slice(2, 7);
const READ = `get_account_${RUN}`;
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

async function say(page, text) {
  const box = page.getByRole('textbox', { name: /Message|Ask/ }).first();
  await box.waitFor({ timeout: 60_000 });
  await box.fill(text);
  const sent = page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }).catch(() => undefined);
  await page.locator('button[aria-label="Send"]').first().click();
  await sent;
  await page.getByRole('button', { name: 'Stop', exact: true }).waitFor({ state: 'hidden', timeout: 90_000 }).catch(() => undefined);
}

await withUiStack(
  async (consoleUrl, stack) => {
    // Team writes need approval only once the admin turns the policy on; it refuses earlier tokens, so people sign in after.
    await writeApprovalsOn();
    const S = await as(SAM, 'team_security');
    await call('POST', `${tools}/v1/egress/hosts`, S, { value: stack.bank.host, note: 'uc-753' });
    await call('POST', `${tools}/v1/egress/ranges`, S, { value: stack.bank.range, note: 'uc-753' });
    const J = await as(JAMES);
    const made = await call('POST', `${tools}/v1/tool-modules/blank`, J, { displayName: `Accounts ${RUN}`, name: `accounts-${RUN}`, type: 'http' });
    const moduleId = made.data?.id;
    const url = `https://${stack.bank.host}/v1/accounts/{accountId}`;
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: READ, description: 'Read an account', access: 'read', method: 'GET', url });
    const added = await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: WRITE, description: 'Freeze an account', access: 'write', method: 'POST', url: `${url}/holds` });
    const opId = added.data?.operations?.find((o) => o.name === WRITE)?.id;
    await call('PATCH', `${tools}/v1/tool-modules/${moduleId}/operations/${opId}`, J, { approvers: 1, requiresApproval: true });
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/reviews`, J, { note: 'uc-753' });
    await approveToolReview(moduleId, await as(NADIA, 'team_security'), J);
    // agents-service reads the tool directory through a 30-second cache; the grant names the tools once they are offered.
    await until(async () => ((await call('GET', `${agents}/v1/tools/options?search=${WRITE}`, J)).data?.data ?? []).some((o) => o.id === WRITE), 60);
    const agent = (await call('POST', `${agents}/v1/agents`, J, { name: `Desk ${RUN}`, role: 'Reads and freezes accounts' })).data;
    const granted = (await call('PATCH', `${agents}/v1/agents/${agent.id}`, J, { toolIds: [READ, WRITE] })).data;
    await call('POST', `${agents}/v1/agents/${agent.id}/publish-requests`, J, { version: granted.version, note: 'uc-753' });
    const ran = async (name) => ((await call('GET', `${tools}/v1/executions?tool=${name}`, J)).data?.data ?? []).filter((r) => r.status === 'ok');

    const browser = await chromium.launch();
    const errors = [];
    try {
      const james = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await james.goto(`${consoleUrl}/chat?agent=${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await say(james, `call ${READ} ${JSON.stringify({ accountId: 'CHQ-2219' })}`);
      await james.waitForURL(/\/chat\/[^/?#]+$/, { timeout: 60_000 }).catch(() => undefined);
      const thread = /\/chat\/([^/?#]+)/.exec(james.url())?.[1];
      const answered = await until(async () => (await ran(READ)).length === 1, 60);
      const readCard = await james.getByTestId('approval-waiting-on').count();
      check('1 the read runs at once in the chat, with no approval card', Boolean(answered) && readCard === 0, { answered, readCard });

      await say(james, `call ${WRITE} ${JSON.stringify({ accountId: 'CHQ-2219' })}`);
      const waiting = await james.getByTestId('approval-waiting-on').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      // Non-vacuous: no write row exists while the card waits, so the one row after approval is the approval's doing.
      check('2 the write stops on a waiting card and nothing has run', waiting && (await ran(WRITE)).length === 0, { waiting });

      const maya = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      await maya.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(thread ?? '')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const decided = await approve(maya);
      const rows = await until(async () => {
        const r = await ran(WRITE);
        return r.length ? r : undefined;
      }, 60);
      check('3 Maya approves in Human Tasks and the write runs once', decided.status === 200 && rows?.length === 1, { status: decided.status, runs: rows?.length, said: decided.said.slice(0, 200) });

      await james.reload({ waitUntil: 'domcontentloaded' });
      const settled = await james.getByTestId('approval-waiting-on').count();
      check('4 James\'s chat no longer shows the card waiting', settled === 0, { settled });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true, gateway: true } },
);

finish();
