// uc-140 the demo walk, ui layer: docs/usecases/console/demo-walk.md, following docs/console/demo-script.md. Runs against the shared stack as it is demoed
// (`make up AUTH=platform`, console on :3016, the chat alias on whatever model the stack serves), so every step is what
// a person sees there. Each step reports on its own; one that fails does not hide the next.
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { check, chromium, finish } from '@ops-ai/usecase-runner/harness';

const ROOT = fileURLToPath(new URL('../../../../', import.meta.url));
const CONSOLE = `http://localhost:${process.env.OPS_CONSOLE_PORT ?? 3016}`;
const AGENTS = `http://127.0.0.1:${process.env.OPS_AGENTS_PORT ?? 8700}`;
const PLATFORM = `http://127.0.0.1:${process.env.OPS_PLATFORM_PORT ?? 8710}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const OMAR = 'o.haddad@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
// A turn on a real model takes several model calls of a few seconds each.
const TURN = 180_000;

const tokenFor = async (email) => (await (await fetch(`${PLATFORM}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;

// UC140_FROM=c starts the walk at scenario c, so a walk cut short resumes without repeating real model calls.
const FROM = process.env.UC140_FROM ?? 'a';
// UC140_ONLY=e,f runs just those scenarios.
const ONLY = process.env.UC140_ONLY?.split(',');

const pages = [];
const SHOTS = process.env.UC140_SHOTS;

async function step(name, body) {
  if (name[0] < FROM || (ONLY && !ONLY.includes(name[0]))) return;
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    // Where each signed-in person's page stood when the step failed.
    if (SHOTS) for (const [who, pg] of pages) await pg.screenshot({ path: `${SHOTS}/uc140-${name[0]}-${who.split('@')[0]}.png` }).catch(() => {});
  }
}

async function signIn(browser, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  // Library Playwright waits forever by default; a control that is not there fails the step instead of the run.
  page.setDefaultTimeout(60_000);
  pages.push([email, page]);
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${CONSOLE}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

/** Starts a chat with `agent`, sends `text` and waits for the reply to finish; the reply's element. */
async function ask(page, agent, text) {
  await page.goto(`${CONSOLE}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByRole('combobox', { name: 'Agent' }).click({ timeout: 120_000 });
  await page.getByRole('option', { name: new RegExp(`^${agent}`) }).click();
  const box = page.getByRole('textbox', { name: 'Message' });
  await box.fill(text);
  const done = page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: TURN });
  await box.press('Enter');
  await (await done).finished();
  await page.getByText('Thinking…').waitFor({ state: 'detached', timeout: TURN }).catch(() => undefined);
  return page.locator('main');
}

const browser = await chromium.launch();
const errors = [];
try {
  const james = await signIn(browser, JAMES, errors);

  await step('a the hardship skill loads and the comparison cites the product sheet', async () => {
    const reply = await ask(james, "Advisor's Helper", 'My client lost her job. Compare Savings Plus and Money Market for her.');
    const skill = await reply.getByTestId('loaded-skills').count();
    const text = await reply.innerText();
    check('a the hardship skill loads and the comparison cites the product sheet', skill > 0 && /Retail Product Sheet/.test(text), { skill, tail: text.slice(-400) });
  });

  await step('b the Savings Plus rate against Money Market, each cited', async () => {
    const reply = await ask(james, "Advisor's Helper", 'What is the interest rate on Savings Plus, and how does it compare with Money Market?');
    const text = await reply.innerText();
    check('b the Savings Plus rate against Money Market, each cited', /3\.10/.test(text) && /3\.65|3\.90/.test(text) && /Retail Product Sheet/.test(text), text.slice(-400));
  });

  await step('b a guardrail refuses an investment question and names itself', async () => {
    const reply = await ask(james, "Advisor's Helper", 'Should my client buy Harbor & Pine shares?');
    const refusal = reply.getByTestId('guardrail-refusal');
    await refusal.waitFor({ timeout: 60_000 });
    check('b a guardrail refuses an investment question and names itself', /No investment advice/.test(await refusal.innerText()), await refusal.innerText());
  });

  await step('c the agent finds Priya in the bank and lists her accounts, no failed call', async () => {
    const reply = await ask(james, "Advisor's Helper", 'What does Priya Natarajan have with us?');
    const text = await reply.innerText();
    const failed = await reply.getByText('Error', { exact: true }).count();
    check('c the agent finds Priya in the bank and lists her accounts, no failed call', /search_customers/.test(text) && /get_customer|list_accounts/.test(text) && /CHQ-|SAV-|BUS-/.test(text) && failed === 0, { failed, tail: text.slice(-500) });
  });

  await step('d a wire hold waits for two approvers in Human Tasks and is placed', async () => {
    const reviewsAs = async (email) => {
      const res = await fetch(`${AGENTS}/reviews?page=1&pageSize=200`, { headers: { Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': 'team_ops' } });
      const body = (await res.json()).data;
      return (Array.isArray(body) ? body : (body?.data ?? [])).map((r) => r.id);
    };
    const before = new Set(await reviewsAs(MAYA));
    const reply = await ask(james, 'Wire Fraud Sentinel', 'Wire W-88213 for $48,500 went to a payee added today. Put a 24 hour hold on it.');
    await reply.getByTestId('approval-waiting-on').first().waitFor({ timeout: 60_000 });
    let reviewId = '';
    for (let i = 0; i < 20 && !reviewId; i++) {
      reviewId = (await reviewsAs(MAYA)).find((id) => !before.has(id)) ?? '';
      if (!reviewId) await new Promise((r) => setTimeout(r, 1_000));
    }
    if (!reviewId) throw new Error('no new review in Human Tasks for the hold');
    const statuses = [];
    for (const email of [MAYA, OMAR]) {
      const person = await signIn(browser, email, errors);
      await person.goto(`${CONSOLE}/reviews?review=${encodeURIComponent(reviewId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const form = person.getByTestId('review-decision-form');
      await form.waitFor({ timeout: 60_000 });
      const decided = person.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$|\/actions$/.test(r.url()), { timeout: 120_000 });
      await form.getByRole('button', { name: /^Approve/ }).first().click();
      const stepUp = person.getByRole('dialog', { name: 'Confirm it is you' });
      if (await stepUp.waitFor({ timeout: 5_000 }).then(() => true, () => false)) {
        await person.locator('#reauth-secret').fill(PASSWORD);
        await person.getByTestId('reauth-submit').click();
      }
      statuses.push((await decided).status());
    }
    await james.getByText(/hold (is )?(now )?in place|placed/i).last().waitFor({ timeout: TURN }).catch(() => undefined);
    const after = await james.locator('main').innerText();
    check('d a wire hold waits for two approvers in Human Tasks and is placed', statuses.length === 2 && statuses.every((s) => s < 300) && /hold/i.test(after.slice(-600)), { reviewId, statuses, tail: after.slice(-300) });
  });

  await step('e the latest Customer lookup (seed walk) run opens with each step, succeeded', async () => {
    await james.goto(`${CONSOLE}/workflows/runs`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    // As a person would among many runs: the Workflow filter, then the newest row.
    await james.locator('main').getByRole('button', { name: 'Workflow', exact: true }).click();
    await james.getByRole('option', { name: /Customer lookup \(seed walk\)/ }).click();
    await james.keyboard.press('Escape');
    const row = james.locator('[data-testid^="runner-run-row-"]').filter({ hasText: 'Customer lookup (seed walk)' }).first();
    await row.waitFor({ timeout: 60_000 });
    await row.click();
    await james.waitForURL(/\/workflows\/runs\/wfrun_/, { timeout: 60_000 });
    const status = (await james.getByTestId('run-status').innerText({ timeout: 60_000 })).trim();
    const steps = await james.getByTestId('run-step').count();
    check('e the latest Customer lookup (seed walk) run opens with each step, succeeded', /succeeded/i.test(status) && steps > 1, { status, steps });
  });

  await step('f the advisor runs the customer summary workflow and the run opens from its card', async () => {
    const reply = await ask(james, "Advisor's Helper", 'Run the customer summary workflow for Priya Natarajan.');
    const text = await reply.innerText();
    // The run link sits in the tool card's detail, shown once the card is opened.
    await reply.getByText('workflow__customer_summary').last().click();
    const open = reply.getByRole('link', { name: 'Open run' }).last();
    const href = await open.getAttribute('href', { timeout: 15_000 }).catch(() => null);
    if (href) await open.click();
    const opened = href ? await james.waitForURL(/\/workflows\/runs\/wfrun_/, { timeout: 60_000 }).then(() => true, () => false) : false;
    check('f the advisor runs the customer summary workflow and the run opens from its card', /customer.summary/i.test(text) && /Priya/.test(text) && opened, { href, opened, tail: text.slice(-300) });
  });

  await step('g an emailed levy notice becomes a case per debtor, a hold, approved replies and the sender\'s replies', async () => {
    // The sample team's walk (make demo-walk) emails the notice and decides each Human Task as the team's approver.
    let out;
    try {
      out = execFileSync('make', ['demo-walk'], { cwd: ROOT, encoding: 'utf8', timeout: 600_000 });
    } catch (e) {
      out = `${e.stdout ?? ''}`;
    }
    const mail = ['email started the intake', 'sender thanked', 'case per debtor', 'hold worked out by code', 'reply waits for approval', 'second reply'];
    const lines = out.split('\n').filter((l) => /^(PASS|FAIL)/.test(l));
    const passed = mail.every((m) => lines.some((l) => l.startsWith('PASS') && l.includes(m)));
    check('g an emailed levy notice becomes a case per debtor, a hold, approved replies and the sender\'s replies', passed, { lines });
  });

  check('no page errors', errors.length === 0, errors.slice(0, 3));
} finally {
  await browser.close();
}
finish();
