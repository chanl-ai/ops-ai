// uc-055 a bank API goes from import to a governed agent call, ui layer: docs/usecases/console/tool-lifecycle-end-to-end.md.
// Signed in through platform-service as the seeded people; tools-service reads the fake bank over https, and the agents
// service (scripted model, no provider) takes its tools from tools-service. Each step is checked on its own, so one
// failing step still lets the later ones report.
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { grantTools, openHeldChatWrite } from '../../lib/workflow_ui.mjs';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const AGENT = 'ag_branch';
const JAMES = 'j.richardson@harborpine.example';
const NADIA = 'n.petrov@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
// Egress is changed only by an admin of the Security team (c-079).
const SAM = 's.adeyemi@harborpine.example';
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const headers = async (email, team = 'team_ops') => ({ Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });

/** Runs one step; a throw fails that step's check with the error and leaves the next steps to run. */
async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 300));
    return undefined;
  }
}

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

async function chat(page, consoleUrl, text) {
  await page.goto(`${consoleUrl}/chat?agent=${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const box = page.getByLabel('Message');
  await box.waitFor({ timeout: 120_000 });
  await box.fill(text);
  const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
  // The composer's Send is the one labelled Send; a message's own actions can carry the same text.
  await page.locator('button[aria-label="Send"]').click();
  const res = await sent;
  // The reply streams; wait for its end, but never past 60 s, so a stream that stays open cannot hang the run.
  await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
  return res;
}


await withUiStack(
  async (consoleUrl, stack) => {
    const browser = await chromium.launch();
    const errors = [];
    let moduleId;
    try {
      // 1. The Security admin allows the bank's host and the private range it serves on.
      await step('1 Sam allows the bank host and range', async () => {
        const P = await headers(SAM, 'team_security');
        const host = await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: P, body: JSON.stringify({ value: stack.bank.host, note: 'uc-055' }) });
        const range = await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: P, body: JSON.stringify({ value: stack.bank.range, note: 'uc-055' }) });
        check('1 Sam allows the bank host and range', host.status === 201 && range.status === 201, { host: host.status, range: range.status });
      });

      const james = await signIn(browser, consoleUrl, JAMES, errors);

      // 2. Import: GET as Read and selected, POST as Write and opt-in; the write's stub is the spec's example.
      await step('2 James imports the open spec and saves the draft', async () => {
        await james.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await james.getByTestId('import-operations').click({ timeout: 120_000 });
        const dialog = james.getByRole('dialog', { name: 'Import operations' });
        await dialog.waitFor({ timeout: 30_000 });
        await dialog.getByText('OpenAPI', { exact: false }).first().click();
        await dialog.locator('#spec-url').fill(`https://${stack.bank.host}/v1/openapi-open.json`);
        await dialog.getByRole('button', { name: 'Next' }).click();
        await dialog.getByLabel('Access for get_account').waitFor({ timeout: 60_000 });
        await dialog.locator('#op-place_hold').click();
        const saved = armed(james.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/tool-modules$/.test(r.url()), { timeout: 60_000 }));
        await dialog.getByRole('button', { name: 'Save draft' }).click();
        const res = await saved;
        const made = res?.ok() ? (await res.json()).data : null;
        moduleId = made?.id;
        const ops = Object.fromEntries((made?.operations ?? []).map((o) => [o.name, o]));
        check('2 James imports the open spec and saves the draft', res?.status() === 201 && ops.get_account?.access === 'read' && ops.place_hold?.access === 'write', { status: res?.status(), access: Object.fromEntries(Object.entries(ops).map(([k, o]) => [k, o.access])) });
      });

      // 3. The owner requests a security review from the module page.
      await step('3 James requests a security review', async () => {
        await james.goto(`${consoleUrl}/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await james.getByTestId('header-request-review').click({ timeout: 120_000 });
        const asked = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${moduleId}/reviews`), { timeout: 60_000 }));
        await james.getByRole('dialog', { name: 'Request a security review' }).getByRole('button', { name: 'Request review' }).click();
        const res = await asked;
        check('3 James requests a security review', res?.status() === 200 && (await res.json()).data?.status === 'in_review', res?.status());
      });

      // 4. Security approves it in Human Tasks, where every review is decided (c-163), which publishes it.
      await step('4 Nadia approves the module in Human Tasks and it publishes', async () => {
        const nadia = await signIn(browser, consoleUrl, NADIA, errors);
        const J = await headers(JAMES);
        const waiting = (await (await fetch(`${tools}/v1/tool-modules/${moduleId}`, { headers: J })).json()).data.versions.find((v) => v.status === 'in_review');
        await nadia.goto(`${consoleUrl}/reviews?review=${waiting.reviewId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const decided = armed(nadia.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/reviews/${waiting.reviewId}/decision`), { timeout: 60_000 }));
        await nadia.getByRole('button', { name: 'Approve and publish' }).click({ timeout: 120_000 });
        const res = await decided;
        const after = (await (await fetch(`${tools}/v1/tool-modules/${moduleId}`, { headers: J })).json()).data;
        check('4 Nadia approves the module in Human Tasks and it publishes', res?.status() === 200 && after?.status === 'published', { status: res?.status(), state: after?.status });
      });

      // 5. The owner tries each operation with no workflow approval: the read for real, the write from the stub.
      await step('5 (c-048 T008) James tries the read for real and the write from the stub, as owner', async () => {
        const panel = james.getByTestId('module-test-panel');
        const results = {};
        for (const op of ['get_account', 'place_hold']) {
          // Each operation is tried on its own workbench (c-088).
          await james.goto(`${consoleUrl}/tools/${moduleId}/operations/${op}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await panel.waitFor({ timeout: 120_000 });
          // The panel starts on the mock; the owner's real read is the Test environment target.
          await panel.getByRole('radio', { name: 'Test environment' }).or(panel.getByRole('button', { name: 'Test environment' })).first().click();
          const input = panel.locator('#t-accountId');
          if (await input.count()) await input.fill('CHQ-2219');
          const ran = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/tool-modules/${moduleId}/test`), { timeout: 60_000 }));
          await panel.getByRole('button', { name: 'Run' }).click();
          const res = await ran;
          results[op] = { status: res?.status(), sent: JSON.parse(res?.request().postData() ?? '{}'), ...(res ? (await res.json().catch(() => ({}))).data ?? {} : {}) };
        }
        const read = results.get_account;
        const write = results.place_hold;
        check(
          '5 (c-048 T008) James tries the read for real and the write from the stub, as owner',
          read?.status === 200 && read.stubbed === false && read.reachedHost === stack.bank.host && write?.status === 200 && write.stubbed === true,
          { read: { status: read?.status, decision: read?.decision, reasons: read?.reasons, stubbed: read?.stubbed, reachedHost: read?.reachedHost, sent: read?.sent }, write: { status: write?.status, decision: write?.decision, reasons: write?.reasons, stubbed: write?.stubbed, sent: write?.sent } },
        );
      });

      // 6. Grant both operations to Branch Concierge, save the draft and publish it.
      await step('6 James grants both operations to Branch Concierge and publishes it', async () => {
        await james.goto(`${consoleUrl}/agents/${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        // The agent page saves each edit into its draft by itself; the save after the last grant holds every tool.
        const patched = armed(james.waitForResponse((r) => r.request().method() === 'PATCH' && r.url() === `${agents}/v1/agents/${AGENT}` && ['get_account', 'place_hold'].every((op) => (r.request().postData() ?? '').includes(`"${op}"`)), { timeout: 60_000 }));
        await grantTools(james, ['get_account', 'place_hold'], JAMES);
        const patchRes = await patched;
        const saved = patchRes ? (await patchRes.json()).data : undefined;
        await james.getByTestId('request-agent-publish').click({ timeout: 60_000 });
        const publish = james.getByRole('dialog', { name: /^(Request publish of|Publish) v/ });
        await publish.getByLabel('What changed').fill('Holds API operations');
        const requested = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/agents/${AGENT}/publish-requests`), { timeout: 60_000 }));
        await publish.getByRole('button', { name: /^(Request publish|Publish)$/ }).click();
        const pubRes = await requested;
        const review = pubRes ? (await pubRes.json()).data : undefined;
        const held = saved?.toolIds ?? [];
        check('6 James grants both operations to Branch Concierge and publishes it', patchRes?.status() === 200 && held.includes('get_account') && held.includes('place_hold') && pubRes?.status() === 201 && review?.status === 'approved', { patch: patchRes?.status(), toolIds: held, publish: pubRes?.status(), review: review?.status });
      });

      // 7. A chat read runs through the gateway.
      await step('7 a chat read runs get_account', async () => {
        await chat(james, consoleUrl, 'call get_account {"accountId": "CHQ-2219"}');
        const replied = await james.getByText('Here is what I found.').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
        check('7 a chat read runs get_account', replied, (await james.locator('main').innerText().catch(() => '')).slice(-400));
      });

      // 8. A chat write waits for an approval and sends nothing.
      let heldThread;
      await step('8 a chat write holds for approval', async () => {
        await chat(james, consoleUrl, 'call place_hold {"accountId": "CHQ-2219"}');
        heldThread = /\/chat\/([^/?#]+)/.exec(james.url())?.[1];
        // The person who asked waits on someone else: the card names who decides, with no Approve of his own.
        const card = await james.getByTestId('approval-waiting-on').last().waitFor({ timeout: 60_000 }).then(() => true, () => false) && (await james.getByRole('button', { name: /^Approve/ }).count()) === 0;
        const J = await headers(JAMES);
        const calls = ((await (await fetch(`${tools}/v1/tool-modules/${moduleId}/activity`, { headers: J })).json()).data?.recent ?? []).filter((c) => c.target === 'place_hold' && c.status === 'ok');
        check('8 a chat write holds for approval', card && calls.length === 0, { card, sentWrites: calls.length, thread: heldThread });
      });

      // 9. An approver on the module's team decides it in Reviews; the write runs once.
      await step('9 (c-048 T013) Maya approves the held write in Reviews and it runs once', async () => {
        const maya = await signIn(browser, consoleUrl, MAYA, errors);
        const form = await openHeldChatWrite(maya, consoleUrl, heldThread);
        const decided = armed(maya.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 60_000 }));
        await form.getByRole('button', { name: 'Approve', exact: true }).click();
        const res = await decided;
        const J = await headers(JAMES);
        // The approval resumes the conversation, which then makes the call; give it a moment to land.
        let sent = [];
        for (let i = 0; i < 10 && sent.length === 0; i++) {
          sent = ((await (await fetch(`${tools}/v1/tool-modules/${moduleId}/activity`, { headers: J })).json()).data?.recent ?? []).filter((c) => c.target === 'place_hold' && c.status === 'ok');
          if (sent.length === 0) await new Promise((r) => setTimeout(r, 2_000));
        }
        check('9 (c-048 T013) Maya approves the held write in Reviews and it runs once', res?.status() === 200 && sent.length === 1, { decision: res?.status(), sent: sent.length });
      });

      // 10. The module's Activity tab shows the calls.
      await step("10 the module's Activity tab lists the get_account call", async () => {
        await james.goto(`${consoleUrl}/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const loaded = armed(james.waitForResponse((r) => r.request().method() === 'GET' && r.url().endsWith(`/v1/tool-modules/${moduleId}/activity`), { timeout: 60_000 }));
        await james.getByRole('tab', { name: /^Activity/ }).click({ timeout: 60_000 });
        const res = await loaded;
        const body = res ? (await res.json()).data : undefined;
        const shown = await james.getByText('get_account').first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
        check("10 the module's Activity tab lists the get_account call", res?.status() === 200 && shown && (body?.recent ?? []).some((c) => c.target === 'get_account' && c.status === 'ok'), { status: res?.status(), shown });
      });

      // 11. An operation that stops being offered shows on the agent as no longer offered, with Remove.
      await step('11 (c-048 T010/T011) a hidden operation shows as no longer offered on the agent, with Remove', async () => {
        const J = await headers(JAMES);
        const detail = (await (await fetch(`${tools}/v1/tool-modules/${moduleId}`, { headers: J })).json()).data;
        const op = detail.operations.find((o) => o.name === 'get_account');
        const hid = await fetch(`${tools}/v1/tool-modules/${moduleId}/operations/${op.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ enabled: false }) });
        const pub = await fetch(`${tools}/v1/tool-modules/${moduleId}/versions`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'get_account hidden' }) });
        // Hiding an operation is a major change: it opens a Security review, and calls and grants keep the published
        // operation until Nadia approves (tools-service served_operations). The module is read as its owner, since
        // Security's own team does not see Operations' modules.
        const N = await headers(NADIA, 'team_security');
        const waitingAgain = ((await (await fetch(`${tools}/v1/tool-modules/${moduleId}`, { headers: J })).json()).data?.versions ?? []).find((v) => v.status === 'in_review');
        const approved = waitingAgain ? ((await approveToolReview(moduleId, N, J)).status === 'published' ? 200 : 'not published') : 'no review';
        // agents-service keeps each tenant's tool directory for 30 s (activities/tool_directory.py, ttl_s), so the hidden
        // operation is offered until that answer expires; the page is reopened until it is not, for at most 45 s.
        // Grants no longer offered are listed under the tools picker (c-135), not inside a dialog.
        const grant = james.getByTestId('stale-grants');
        let stale = false;
        for (const until = Date.now() + 45_000; !stale && Date.now() < until; ) {
          await james.goto(`${consoleUrl}/agents/${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          stale = await grant.getByText('No longer offered').waitFor({ timeout: 5_000 }).then(() => true, () => false);
          if (!stale) await james.waitForTimeout(5_000);
        }
        const remove = stale && (await grant.getByRole('button', { name: /Remove/ }).count()) > 0;
        // What agents-service holds, so a failure says which side kept offering the operation.
        const viewAgent = (await (await fetch(`${agents}/v1/agents/${AGENT}`, { headers: J })).json()).data;
        const offered = ((await (await fetch(`${agents}/v1/tools`, { headers: J })).json()).data ?? []).filter((t) => t.id === 'get_account').map((t) => t.moduleId);
        const opsNow = (await (await fetch(`${tools}/v1/tool-modules/${moduleId}`, { headers: J })).json()).data;
        check('11 (c-048 T010/T011) a hidden operation shows as no longer offered on the agent, with Remove', hid.status === 200 && pub.status === 200 && approved === 200 && stale && remove, { hide: hid.status, publish: pub.status, approved, stale, remove, toolIds: viewAgent?.toolIds, staleToolIds: viewAgent?.staleToolIds, offeredBy: offered, status: opsNow?.status, enabled: opsNow?.operations?.find((o) => o.name === 'get_account')?.enabled, pending: opsNow?.pendingChanges?.length });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true, gateway: true } },
);

finish();
