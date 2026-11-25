// uc-768 one create form holds a name to the same rule the server keeps, ui layer: docs/usecases/console/name-limits-on-a-form.md.
// Signed in through platform-service as James; the New guardrail dialog is the one form. A 200-letter name saves, a
// 201-letter and a blank one are refused with a sentence and send nothing, and a Chinese name saves.
import { AGENTS_PORT, check, chromium, consoleSignIn, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, agents, as } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const letters = (n) => `N${TAG}`.padEnd(n, 'x');
const CHINESE = `客户风险守则${TAG}`;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const J = await as(JAMES);
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const posts = [];
      page.on('request', (r) => r.method() === 'POST' && r.url().includes(`:${AGENTS_PORT}/v1/guardrails`) && posts.push(r.url()));
      const dialog = page.getByRole('dialog');
      const stored = async () => (await (await fetch(`${agents}/v1/guardrails?pageSize=100`, { headers: J })).json()).data?.data?.map((g) => g.name) ?? [];
      const open = async () => {
        await page.goto(`${consoleUrl}/build/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('new-guardrail-button').click({ timeout: 120_000 });
        await dialog.getByLabel('Blocked topics').fill('crypto tips');
        await dialog.getByLabel('Blocked topics').press('Enter');
        await dialog.getByLabel('Message instead of an answer').fill('I cannot give tips.');
      };
      const submit = async (name) => {
        await dialog.getByLabel('Name').fill(name);
        const made = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/guardrails'), { timeout: 8_000 }).catch(() => null);
        await dialog.getByTestId('guardrail-submit').click();
        return made;
      };

      await step('1 a 200-letter name saves', async () => {
        await open();
        const res = await submit(letters(200));
        await dialog.waitFor({ state: 'hidden', timeout: 15_000 }).catch(() => undefined);
        const names = await stored();
        check('1 a 200-letter name saves', res?.status() === 201 && names.some((n) => n === letters(200)), { status: res?.status(), lengths: names.map((n) => n.length) });
      });

      await step('2 a 201-letter name is refused with a sentence and sends nothing', async () => {
        await open();
        const before = posts.length;
        const res = await submit(letters(201));
        const message = (await dialog.getByText(/at most 200 characters/).first().innerText().catch(() => '')).trim();
        await shootBothWidths(page, 'console', 'uc-768-name-too-long', async () => page.waitForTimeout(300));
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('2 a 201-letter name is refused with a sentence and sends nothing', res === null && posts.length === before && message === 'The name is at most 200 characters.' && (await dialog.isVisible()), { message, sent: posts.length - before });
      });

      await step('3 a blank name is refused with a sentence and sends nothing', async () => {
        const before = posts.length;
        const res = await submit('   ');
        const message = (await dialog.getByText('Name the guardrail.').first().innerText().catch(() => '')).trim();
        check('3 a blank name is refused with a sentence and sends nothing', res === null && posts.length === before && message === 'Name the guardrail.' && (await dialog.isVisible()), { message, sent: posts.length - before });
      });

      await step('4 a Chinese name saves and is listed under its own letters', async () => {
        const res = await submit(CHINESE);
        await dialog.waitFor({ state: 'hidden', timeout: 15_000 }).catch(() => undefined);
        const names = await stored();
        check('4 a Chinese name saves and is listed under its own letters', res?.status() === 201 && names.includes(CHINESE), { status: res?.status(), names: names.map((n) => n.slice(0, 12)) });
      });

      await step('5 the server refuses a 201-letter name too, with a sentence', async () => {
        const r = await fetch(`${agents}/v1/guardrails`, { method: 'POST', headers: J, body: JSON.stringify({ kind: 'blocked_topics', name: letters(201), owner: 'Compliance', topics: ['crypto tips'], scopes: {}, message: 'No.', holdUntilChecked: false }) });
        const body = await r.json().catch(() => ({}));
        check('5 the server refuses a 201-letter name too, with a sentence', r.status >= 400 && r.status < 500 && /200/.test(body.error?.message ?? ''), { status: r.status, error: body.error });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
