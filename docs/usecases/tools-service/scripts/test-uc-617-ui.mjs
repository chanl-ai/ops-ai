// uc-617 an app that fails says why, ui layer: docs/usecases/tools-service/an-app-that-fails-says-why.md, story S3
// (steps 6-6c). James (builder, no Security role) saves a REST tool on a host nobody listed: the import dialog says it
// waits for Security, and nothing is saved. Sam (Security admin) decides it in Human Tasks, where the task shows the
// host, the app and who asked, with Approve and Refuse. A refusal's reason reaches James's next save; an approval lets
// it through. A private stack: platform sign-in, tools-service and agents-service.
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const REFUSED = 'held.uc617.example';
const ALLOWED = 'allowed.uc617.example';
const WHY = 'not a system the bank uses';
const SHOTS = evidenceDir('617', 'uc');

const tokenFor = async (email) =>
  (
    await (
      await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })
    ).json()
  ).data.token;
const as = async (email, team) => ({ Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': team });

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

/** Import operations, one HTTP operation on `host`, saved; the dialog stays open on anything but a saved tool. */
async function saveHttpTool(page, consoleUrl, host) {
  await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('import-operations').click({ timeout: 120_000 });
  await page.locator('label[for="mk-http"]').click();
  await page.getByTestId('import-next').click();
  await page.locator('#http-url').fill(`https://${host}/v1/ping`);
  await page.locator('#http-name').fill('ping_desk');
  await page.getByTestId('import-save').click();
}

/** Sam's open Security task for `host`, read from Human Tasks' own list. */
async function taskFor(host) {
  const sam = await as(SAM, 'team_security');
  const rows = (await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/reviews?pageSize=200&kind=egress_host`, { headers: sam })).json()).data?.data ?? [];
  return rows.find((r) => r.egressHost?.host === host);
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      await step('6 James saves a tool on an unlisted host: the dialog says it waits for Security, and nothing is saved', async () => {
        const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
        await page.setViewportSize({ width: 1280, height: 900 });
        await saveHttpTool(page, consoleUrl, REFUSED);
        const held = page.getByTestId('host-held');
        await held.waitFor({ timeout: 30_000 });
        const text = (await held.innerText()).replace(/\s+/g, ' ');
        const before = (await page.getByTestId('egress-host-notice').innerText()).replace(/\s+/g, ' ');
        await page.screenshot({ path: join(SHOTS, 'host-held-1280.png') });
        const james = await as(JAMES, 'team_ops');
        const saved = (await (await fetch(`http://127.0.0.1:${TOOLS_PORT}/v1/tool-modules?pageSize=200&search=ping`, { headers: james })).json()).data?.data ?? [];
        const task = await taskFor(REFUSED);
        check(
          '6 James saves a tool on an unlisted host: the dialog says it waits for Security, and nothing is saved',
          text.includes(`Waiting for Security to allow ${REFUSED}`) && /asks a Security admin/.test(before) && saved.length === 0 && task?.status === 'pending',
          { text, before, saved: saved.length, task: task && { id: task.id, status: task.status } },
        );
        await page.context().close();
      });

      await step('6a Sam’s task shows the host, the app and who asked, with Approve and Refuse; Sam refuses with a reason', async () => {
        const task = await taskFor(REFUSED);
        if (!task) throw new Error('setup: no egress_host task for the held host');
        const page = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
        await page.setViewportSize({ width: 1280, height: 900 });
        await page.goto(`${consoleUrl}/reviews/${task.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const panel = page.getByTestId('decision-panel');
        await panel.waitFor({ timeout: 60_000 });
        const body = (await panel.innerText()).replace(/\s+/g, ' ');
        const facts = body.includes(REFUSED) && body.includes('Asked by') && body.includes(JAMES) && /\bApp\b/.test(body);
        const buttons = { approve: await page.getByTestId('review-approve').count(), refuse: await panel.getByRole('button', { name: 'Refuse' }).count(), back: await panel.getByRole('button', { name: /Return to/ }).count() };
        await page.screenshot({ path: join(SHOTS, 'host-task-1280.png') });
        await page.getByTestId('review-reject').click();
        await page.locator('#decision-reason').fill(WHY);
        await page.getByTestId('review-reject').click();
        // Decided tasks leave the open list; the task itself is read by its id.
        const sam = await as(SAM, 'team_security');
        let decided;
        for (let i = 0; i < 20 && decided?.status !== 'rejected'; i++) {
          await page.waitForTimeout(500);
          decided = (await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/reviews/${task.id}`, { headers: sam })).json()).data;
        }
        check(
          '6a Sam’s task shows the host, the app and who asked, with Approve and Refuse; Sam refuses with a reason',
          facts && buttons.approve === 1 && buttons.refuse === 1 && buttons.back === 0 && decided?.status === 'rejected' && decided?.decisionReason === WHY,
          { body: body.slice(0, 300), buttons, status: decided?.status, reason: decided?.decisionReason },
        );
        await page.context().close();
      });

      await step('6b James saves again and reads Sam’s reason in the dialog', async () => {
        const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
        await saveHttpTool(page, consoleUrl, REFUSED);
        const problem = page.getByTestId('save-problem');
        await problem.waitFor({ timeout: 30_000 });
        const text = (await problem.innerText()).replace(/\s+/g, ' ');
        check('6b James saves again and reads Sam’s reason in the dialog', text.includes(`Security refused ${REFUSED}`) && text.includes(WHY), text);
        await page.context().close();
      });

      await step('6c Sam approves another host; James’s next save goes through and opens the tool', async () => {
        const james = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
        await saveHttpTool(james, consoleUrl, ALLOWED);
        await james.getByTestId('host-held').waitFor({ timeout: 30_000 });
        const task = await taskFor(ALLOWED);
        if (!task) throw new Error('setup: no egress_host task for the second host');
        const sam = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
        await sam.goto(`${consoleUrl}/reviews/${task.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await sam.getByTestId('review-approve').click({ timeout: 60_000 });
        for (let i = 0; i < 20 && (await taskFor(ALLOWED)); i++) await sam.waitForTimeout(500);
        await james.getByTestId('import-save').click();
        await james.waitForURL(/\/tools\/[^/]+$/, { timeout: 30_000 });
        const listed = (await (await fetch(`http://127.0.0.1:${TOOLS_PORT}/v1/egress`, { headers: await as(SAM, 'team_security') })).json()).data?.hosts?.find((h) => h.host === ALLOWED);
        check('6c Sam approves another host; James’s next save goes through and opens the tool', !!listed && /\/tools\/[^/]+$/.test(james.url()), { listed, url: james.url() });
        await james.context().close();
        await sam.context().close();
      });
      check('7 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);
finish();
