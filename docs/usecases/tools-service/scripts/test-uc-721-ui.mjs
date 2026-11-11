// uc-721 step 8, ui layer: with the team switch "Ask before an agent changes anything in an app" on and "Ask the person"
// chosen, a chat's write draws an Allow / Deny card for the person who asked; Allow runs it, Deny stops it, and
// another member reading the thread sees no buttons. With "Ask a reviewer" the asker gets no decision and a reviewer
// approves in Human Tasks. Walked as a member (James) and an admin (Priya) at 1440 and 390; screenshots go to SHOTS.
import { mkdirSync } from 'node:fs';
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, PRIYA, as, openHeldChatWrite, until } from '../../lib/workflow_ui.mjs';

const SHOTS = process.env.SHOTS_DIR ?? 'docs/plans/ops-ai/test-results/approvals/chat';
mkdirSync(SHOTS, { recursive: true });
const SAM = 's.adeyemi@harborpine.example';
const NADIA = 'n.petrov@harborpine.example';
const RUN = Math.random().toString(36).slice(2, 7);
const WRITE = `close_ticket_${RUN}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
// Each policy change below raises the permission version, which refuses tokens issued before it (401
// permissions_changed), so a person's headers sign them in again once and retry. Any other refusal throws: a refused
// read must never count as "nothing ran".
const signedIn = async (email, team) => Object.defineProperty(await as(email, team), 'renew', { value: () => as(email, team) });
const call = async (method, url, headers, body) => {
  const send = () => fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  let r = await send();
  if (r.status === 401 && headers.renew) {
    Object.assign(headers, await headers.renew());
    r = await send();
  }
  if (!r.ok) throw new Error(`${method} ${new URL(url).pathname}: ${r.status} ${FLAT(await r.text().catch(() => '')).slice(0, 200)}`);
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};
const FLAT = (s) => (s ?? '').replace(/\s+/g, ' ').trim();
const SIZES = [{ name: '1440', width: 1440, height: 1000 }, { name: '390', width: 390, height: 844 }];

await withUiStack(
  async (consoleUrl, stack) => {
    const S = await as(SAM, 'team_security');
    await call('POST', `${tools}/v1/egress/hosts`, S, { value: stack.bank.host, note: 'uc-721' });
    await call('POST', `${tools}/v1/egress/ranges`, S, { value: stack.bank.range, note: 'uc-721' });
    const J = await signedIn(JAMES);
    const P = await signedIn(PRIYA);
    const made = await call('POST', `${tools}/v1/tool-modules/blank`, J, { displayName: `Tickets ${RUN}`, name: `tickets-${RUN}`, type: 'http' });
    const moduleId = made.data?.id;
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: WRITE, description: 'Close a ticket', access: 'write', method: 'POST', url: `https://${stack.bank.host}/v1/accounts/{accountId}/holds` });
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/reviews`, J, { note: 'uc-721' });
    await (await import('@ops-ai/usecase-runner/harness')).approveToolReview(moduleId, await as(NADIA, 'team_security'), J);
    await until(async () => ((await call('GET', `${agents}/v1/tools/options?search=${WRITE}`, J)).data?.data ?? []).some((o) => o.id === WRITE), 60);
    const agent = (await call('POST', `${agents}/v1/agents`, J, { name: `Closer ${RUN}`, role: 'Closes tickets' })).data;
    const granted = (await call('PATCH', `${agents}/v1/agents/${agent.id}`, J, { toolIds: [WRITE] })).data;
    await call('POST', `${agents}/v1/agents/${agent.id}/publish-requests`, J, { version: granted.version, note: 'uc-721' });
    const rowsOf = async () => ((await call('GET', `${tools}/v1/executions?pageSize=200`, J)).data?.data ?? []).filter((r) => r.target === WRITE);
    const ran = async () => (await rowsOf()).filter((r) => r.status === 'ok' || r.effect === true);

    // The admin's switch, as Govern > Approvals saves it: on, ask the person, test accounts asked too.
    const put = (value) => call('PUT', `${platform}/v1/policies/appChanges`, P, { value }).then((r) => ({ ok: true, status: r.status }), (e) => ({ ok: false, status: String(e).slice(0, 300) }));
    const saved = await put({ ask: true, answer: 'person', reviewerRole: null, testAccountsNeverAsk: false });
    check('1 the admin turns asking on, with the person chosen', saved.ok, saved.status);
    // agents-service reads the tool directory through a 30-second cache; until it turns over an agent's write is
    // refused at the gateway without a card.
    await new Promise((r) => setTimeout(r, 35_000));

    const browser = await chromium.launch();
    const errors = [];
    const failed = [];
    const watch = (page, who) => {
      page.on('console', (m) => m.type() === 'error' && errors.push(`${who} console: ${m.text().slice(0, 200)}`));
      page.on('response', async (r) => {
        if (r.status() < 400) return;
        failed.push(`${who} ${r.request().method()} ${r.status()} ${new URL(r.url()).pathname} ${FLAT(await r.text().catch(() => '')).slice(0, 240)}`);
      });
    };
    /** Signs `email` in at `size`, sends the write in a new chat, and returns the page and thread once the reply ends. */
    async function ask(email, who, size) {
      const page = await consoleSignIn(browser, consoleUrl, email, PASSWORD, errors);
      await page.setViewportSize({ width: size.width, height: size.height });
      watch(page, `${who}@${size.name}`);
      await page.goto(`${consoleUrl}/chat?agent=${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: /Message|Ask/ }).first();
      await box.waitFor({ timeout: 60_000 });
      await box.fill(`call ${WRITE} ${JSON.stringify({ accountId: 'CHQ-2219' })}`);
      await page.locator('button[aria-label="Send"]').first().click();
      await page.waitForURL(/\/chat\/[^/?#]+$/, { timeout: 60_000 }).catch(() => undefined);
      const thread = /\/chat\/([^/?#]+)/.exec(page.url())?.[1];
      return { page, thread };
    }
    const shot = (page, name) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });

    try {
      const plan = [
        { size: SIZES[0], email: JAMES, who: 'member', decide: 'allow' },
        { size: SIZES[0], email: PRIYA, who: 'admin', decide: 'deny' },
        { size: SIZES[1], email: JAMES, who: 'member', decide: 'deny' },
        { size: SIZES[1], email: PRIYA, who: 'admin', decide: 'allow' },
      ];
      let expected = 0;
      let observed = false;
      for (const step of plan) {
        const tag = `${step.who}-${step.size.name}`;
        const { page, thread } = await ask(step.email, step.who, step.size);
        const card = page.getByTestId('ask-first-card').last();
        const shown = await card.waitFor({ timeout: 90_000 }).then(() => true, () => false);
        await page.getByRole('button', { name: 'Stop', exact: true }).waitFor({ state: 'hidden', timeout: 60_000 }).catch(() => undefined);
        await card.getByTestId('ask-first-deny').waitFor({ timeout: 30_000 }).catch(() => undefined);
        await shot(page, `person-card-${tag}`);
        const buttons = shown ? await card.getByRole('button').allInnerTexts() : [];
        check(`2 ${tag}: the asker sees an Allow / Deny card and nothing has run`, shown && (await ran()).length === expected && buttons.some((b) => /^Deny$/.test(b)) && buttons.some((b) => /^Allow$/.test(b)), { shown, buttons, runs: (await ran()).length });
        const box = await card.boundingBox();
        check(`2 ${tag}: the card fits the screen`, !!box && box.x >= 0 && box.x + box.width <= step.size.width + 1, box);

        if (!observed && step.who === 'member') {
          observed = true;
          const maya = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
          await maya.setViewportSize({ width: step.size.width, height: step.size.height });
          watch(maya, 'observer');
          await maya.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await maya.waitForLoadState('networkidle').catch(() => undefined);
          const seen = await maya.getByTestId('ask-first-card').count();
          const decide = await maya.getByTestId('ask-first-allow').count() + (await maya.getByTestId('ask-first-deny').count());
          await shot(maya, `person-card-other-member-${step.size.name}`);
          check('3 a member who did not ask sees no Allow or Deny', decide === 0, { cardDrawn: seen, buttons: decide, page: FLAT(await maya.locator('main').innerText().catch(() => '')).slice(0, 160) });
          await maya.context().close();
        }

        if (step.decide === 'allow') {
          await card.getByTestId('ask-first-allow').click();
          const rows = await until(async () => ((await ran()).length > expected ? await ran() : undefined), 60);
          if (rows?.length > expected) expected = rows.length;
          await page.getByTestId('approval-waiting-on').last().waitFor({ timeout: 30_000 }).catch(() => undefined);
          await shot(page, `person-allowed-${tag}`);
          check(`4 ${tag}: Allow runs the write once, shown in the executions list`, !!rows && rows.length === expected, { runs: rows?.length, all: (await rowsOf()).map((r) => `${r.status}/${r.outcome}/${r.denyReason ?? ''}/${r.effect}`) });
        } else {
          await card.getByTestId('ask-first-deny').click();
          await page.waitForTimeout(8_000);
          await shot(page, `person-denied-${tag}`);
          check(`5 ${tag}: Deny stops it, nothing more ran`, (await ran()).length === expected, { runs: (await ran()).length });
          check(`5 ${tag}: the card no longer offers Allow / Deny`, (await page.getByTestId('ask-first-allow').count()) === 0, FLAT(await card.innerText().catch(() => '')));
        }
        await page.context().close();
      }

      // Ask a reviewer: the asker gets no decision; the reviewer decides in Human Tasks.
      const roles = (await call('GET', `${platform}/v1/roles`, P)).data;
      const list = Array.isArray(roles) ? roles : roles?.data ?? [];
      const reviewerRole = 'reviewer';
      const sw = await put({ ask: true, answer: 'reviewer', reviewerRole, testAccountsNeverAsk: false });
      check('6 the admin switches to Ask a reviewer', sw.ok, { status: sw.status, reviewerRole, roles: list.map((r) => r.id ?? r.name) });
      await new Promise((r) => setTimeout(r, 35_000));
      for (const size of SIZES) {
        const { page, thread } = await ask(JAMES, 'member', size);
        const waiting = await page.getByTestId('approval-waiting-on').last().waitFor({ timeout: 90_000 }).then(() => true, () => false);
        await shot(page, `reviewer-asker-${size.name}`);
        const own = await page.getByTestId('ask-first-card').count();
        const buttons = await page.getByRole('button', { name: /^(Allow|Deny|Approve|Reject|Allow for this chat)$/ }).count();
        check(`7 ${size.name}: the asker is told it waits and gets no decision`, waiting && own === 0 && buttons === 0 && (await ran()).length === expected, { waiting, ownCard: own, buttons, runs: (await ran()).length });
        if (size.name === '1440') {
          const priya = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
          watch(priya, 'reviewer');
          let form;
          try { form = await openHeldChatWrite(priya, consoleUrl, thread); } catch (e) { check('8 the reviewer opens it in Human Tasks', false, String(e).slice(0, 300)); }
          if (form) {
            await shot(priya, 'reviewer-human-tasks-1440');
            const sent = priya.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 90_000 }).catch(() => undefined);
            await form.getByRole('button', { name: /^Approve/ }).click();
            const reauth = priya.getByRole('dialog').filter({ hasText: /Confirm it|password/i });
            if (await reauth.waitFor({ timeout: 10_000 }).then(() => true, () => false)) {
              await reauth.getByLabel(/password/i).first().fill(PASSWORD);
              await reauth.getByRole('button', { name: /confirm|sign in|continue/i }).last().click();
            }
            const res = await sent;
            const rows = await until(async () => ((await ran()).length > expected ? await ran() : undefined), 60);
            if (rows?.length > expected) expected = rows.length;
            check('8 the reviewer approves in Human Tasks and the write runs once', res?.status() === 200 && rows?.length === expected, { status: res?.status(), runs: rows?.length });
          }
          await priya.context().close();
        }
        await page.context().close();
      }
      check('no page errors', errors.length === 0, errors);
      check('no refused requests', failed.length === 0, failed);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true, gateway: true } },
);
finish();
