// uc-771 ui layer: docs/usecases/agents-service/a-builder-takes-a-new-skill.md. The first Ops AI milestone says a builder
// goes from a new skill to its first publish in under ten minutes. James starts on the skills list, makes a skill, writes
// a short plain-text SOP with one guard, saves it and sends it for review; Maya opens the text diff and approves; the
// skill shows as published. Each step's wall-clock seconds and the clicks and typing a person needed are printed; the
// run fails if any step fails or the total is over BUDGET_SECONDS. Platform sign-in, the scripted model, 1440 wide.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, publishReviewOn } from '../../lib/workflow_ui.mjs';
import { setText } from './rich-text.mjs';

const BUDGET_SECONDS = Number(process.env.UC771_BUDGET_SECONDS ?? 600);
const RUN = Math.random().toString(36).slice(2, 6);
const NAME = `Refund request ${RUN}`;
const USE_WHEN = 'Use when a customer asks for a refund.';
const SOP = [
  'Ask for the order number and look the order up.',
  'if they ask for a refund:',
  '    Never refund over 500 without a manager approving it.',
  '    Explain the refund policy and ask them to confirm.',
  'Tell them what happens next.',
].join('\n');

const rows = [];
const actions = { clicks: 0, fields: 0, keys: 0, chars: 0 };
const click = async (locator) => (actions.clicks++, locator.click({ timeout: 60_000 }));
const fill = async (locator, text) => (actions.fields++, (actions.chars += text.length), locator.fill(text, { timeout: 60_000 }));
const press = async (page, key) => (actions.keys++, page.keyboard.press(key));
const typeText = async (page, text) => (actions.fields++, (actions.chars += text.length), page.keyboard.insertText(text));

/** Runs one step, records its seconds and the actions it took, and stops the walk when it fails. */
let current;
async function step(name, fn) {
  const before = { ...actions };
  const t0 = performance.now();
  try {
    await fn();
  } catch (e) {
    const screen = await current?.locator('[role=dialog], [role=alert], main').allInnerTexts().then((t) => t.join(' | ').replace(/\s+/g, ' ').slice(0, 500)).catch(() => '');
    const seconds = (performance.now() - t0) / 1000;
    rows.push({ name, seconds, ok: false });
    check(`${name} (${seconds.toFixed(1)} s)`, false, `${String(e).slice(0, 300)} on screen: ${screen}`);
    throw e;
  }
  const seconds = (performance.now() - t0) / 1000;
  const used = { clicks: actions.clicks - before.clicks, fields: actions.fields - before.fields, keys: actions.keys - before.keys };
  rows.push({ name, seconds, ok: true, ...used });
}

await withUiStack(
  async (consoleUrl) => {
    // Setup, not timed: the team's admin has turned publish review on for skills, as a team that wants a reviewer does.
    await publishReviewOn({ skills: 'always' });
    const browser = await chromium.launch();
    const errors = [];
    try {
      const james = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      current = james;
      const wall = performance.now();
      let reviewUrl;

      await step('1 open the skills list', async () => {
        await james.goto(`${consoleUrl}/build/skills`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await james.getByTestId('new-skill-button').waitFor({ timeout: 60_000 });
      });
      await step('2 create the skill (name, when to use it, Create)', async () => {
        await click(james.getByTestId('new-skill-button'));
        const dialog = james.getByRole('dialog');
        await fill(dialog.getByLabel('Name'), NAME);
        await fill(dialog.getByLabel('Use when'), USE_WHEN);
        await click(james.getByTestId('new-skill-submit'));
        await james.waitForURL(/\/build\/skills\/[^/?#]+/, { timeout: 60_000 });
        await james.getByTestId('rich-text').waitFor({ timeout: 120_000 });
      });
      await step('3 write the SOP with one guard', async () => {
        // The whole text goes in through the Markdown view, which keeps its lines and their indent exactly.
        actions.fields++;
        actions.chars += SOP.length;
        await setText(james, SOP);
        await james.getByTestId('rich-text').locator('p, li', { hasText: 'Never refund over 500' }).first().waitFor({ timeout: 30_000 });
      });
      await step('4 save the draft', async () => {
        const saved = james.locator('[data-testid="save-state"][data-state="saved"]');
        const put = james.waitForResponse((r) => r.request().method() === 'PUT' && /\/v1\/skills\/[^/]+\/draft$/.test(r.url()), { timeout: 60_000 }).catch(() => undefined);
        const save = james.getByTestId('save-skill-draft');
        if (await save.isEnabled().catch(() => false)) await click(save);
        await put;
        await saved.waitFor({ timeout: 60_000 });
      });
      await step('5 send it for review', async () => {
        const publish = james.getByTestId('request-review-button');
        await publish.waitFor({ timeout: 30_000 });
        await click(publish);
        const dialog = james.getByRole('dialog');
        await dialog.waitFor({ timeout: 30_000 });
        await fill(dialog.getByRole('textbox'), 'First version: refunds over 500 need a manager.');
        const sent = james.waitForResponse((r) => r.request().method() === 'POST' && /\/publish-requests$/.test(r.url()), { timeout: 60_000 });
        await click(james.getByTestId('request-review-submit'));
        const res = await sent;
        if (res.status() >= 300) throw new Error(`send for review answered ${res.status()}: ${(await res.text()).slice(0, 200)}`);
        await james.getByTestId('skill-pending-review').waitFor({ timeout: 60_000 });
        reviewUrl = await james.getByTestId('skill-pending-review').getByRole('link').first().getAttribute('href').catch(() => undefined);
      });

      const maya = await (async () => {
        let page;
        await step('6 reviewer signs in', async () => {
          actions.fields += 2;
          actions.clicks += 1;
          page = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
          current = page;
        });
        return page;
      })();
      await step('7 reviewer opens the request and reads the text diff', async () => {
        if (reviewUrl) await maya.goto(new URL(reviewUrl, consoleUrl).toString(), { waitUntil: 'domcontentloaded', timeout: 120_000 });
        else {
          await maya.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await click(maya.getByText(NAME).first());
        }
        await maya.getByTestId('skill-publish-body').waitFor({ timeout: 60_000 });
        const body = await maya.getByTestId('skill-publish-body').innerText();
        if (!/Never refund over 500/.test(body)) throw new Error(`the diff does not show the guard line; the review shows: ${body.replace(/\s+/g, ' ').slice(0, 300)}`);
      });
      await step('8 reviewer approves and the skill publishes', async () => {
        const approve = maya.getByTestId('review-approve');
        await approve.waitFor({ timeout: 30_000 });
        if (!(await approve.isEnabled())) throw new Error(`Approve is disabled: ${(await approve.innerText()).trim()}`);
        const decided = maya.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 90_000 });
        await click(approve);
        // A decision may ask for the password first; whichever comes first ends the wait.
        const reauth = maya.getByRole('dialog').filter({ hasText: /Confirm it|password/i });
        const asked = await Promise.race([reauth.waitFor({ timeout: 90_000 }).then(() => true, () => false), decided.then(() => false, () => false)]);
        if (asked) {
          await fill(reauth.getByLabel(/password/i).first(), PASSWORD);
          await click(reauth.getByRole('button', { name: /confirm|sign in|continue/i }).last());
        }
        const res = await decided;
        if (res.status() !== 200) throw new Error(`approve answered ${res.status()}: ${(await res.text()).slice(0, 200)}`);
      });
      await step('9 the builder sees v1 published', async () => {
        await james.reload({ waitUntil: 'domcontentloaded' });
        await james.getByText(/v1 published/).first().waitFor({ timeout: 60_000 });
      });

      const total = (performance.now() - wall) / 1000;
      for (const r of rows) console.log(`STEP ${r.name}: ${r.seconds.toFixed(1)} s`);
      console.log(`STEP total: ${total.toFixed(1)} s (budget ${BUDGET_SECONDS} s)`);
      console.log(`EFFORT ${actions.clicks} clicks, ${actions.fields} fields typed or pasted (${actions.chars} characters), ${actions.keys} key presses`);
      check(`1 a new skill goes from the list to published in ${total.toFixed(0)} s, under ${BUDGET_SECONDS} s`, rows.every((r) => r.ok) && total <= BUDGET_SECONDS, { total, rows });
      check('2 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
