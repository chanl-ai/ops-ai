// uc-253 a builder tests an agent in the right panel of its page, built from the chat page's components, ui layer:
// docs/usecases/agents-service/test-an-agent-in-its-page-panel.md. James Richardson (builder) tests the advisor on the
// demo stack's fake model: the reply streams in the panel with the chat page's message view, the Why tab explains it,
// Versions and Used in hold the page's old right column, Run as is gone, and at 400 px Test brings the panel into view.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const QUESTION = 'UC229 FUND QUESTION: what should my client know about the Harbor & Pine fund?';
const CORRECTED = "I can't give investment advice. A licensed adviser can talk your client through the fund.";
// Screenshots are kept with the card's evidence; UC253_SHOTS points them anywhere else.
const SHOTS = process.env.UC253_SHOTS ?? join(process.cwd(), '.codeloop', 'evidence', '253');

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/agents/ag_advisor`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const panel = page.getByTestId('agent-test-panel');
      await panel.waitFor({ timeout: 120_000 });
      check('1 the agent page has the test panel beside its settings, and no Run as', (await page.getByTestId('run-as-bar').count()) === 0 && (await page.getByText('Run as', { exact: true }).count()) === 0);

      const box = panel.getByLabel('Message');
      await box.fill(QUESTION);
      await panel.locator('button[aria-label="Send"]').click();
      await panel.getByText(CORRECTED).first().waitFor({ timeout: 120_000 });
      // The chat page's own assistant message renders here: its guardrail note is that component's.
      // The note shows once the reply has settled, a moment after its text.
      await panel.getByTestId('guardrail-refusal').first().waitFor({ timeout: 30_000 }).catch(() => {});
      const note = await panel.getByTestId('guardrail-refusal').count();
      check('2 the reply streams into the panel through the chat page\'s message view', note === 1, { note });

      await panel.getByTestId('why-tab').click();
      const why = await panel.getByTestId('test-steps').innerText();
      check('3 Why names the knowledge searched, the tools called and the guardrail that changed the answer', /knowledge|knowledge bases/i.test(why) && /tool/i.test(why) && why.includes('No investment advice'), why.slice(0, 400));
      // The spend is the stored reply's, read once the thread reloads after the turn.
      await panel.getByTestId('test-step-spent').getByText(/tokens?/).first().waitFor({ timeout: 30_000 }).catch(() => {});
      const spent = await panel.getByTestId('test-step-spent').innerText();
      check('3b Why says what the reply spent: tokens, cost and seconds (c-286)', /\d[\d,]* tokens?/.test(spent) && /\d+\.\d{2}/.test(spent) && / s\b/.test(spent), spent);
      await page.screenshot({ path: join(SHOTS, 'agent-test-panel-why.png'), fullPage: false });

      await panel.getByRole('tab', { name: 'Versions' }).click();
      const versions = await panel.innerText();
      await panel.getByRole('tab', { name: 'Used in' }).click();
      const used = await panel.innerText();
      check('4 Versions and Used in hold what the right column showed: history, workflows and recent runs', /version/i.test(versions) && /(used in|workflow|runs)/i.test(used), { versions: versions.slice(0, 160), used: used.slice(0, 160) });

      mkdirSync(SHOTS, { recursive: true });
      await panel.getByTestId('test-tab').click();
      await page.screenshot({ path: join(SHOTS, 'agent-test-panel-1280.png'), fullPage: false });

      // At phone width the columns stack; Test in the header brings the panel into view, ready to type.
      await page.setViewportSize({ width: 400, height: 860 });
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(500);
      const button = page.getByTestId('test-agent-button');
      await button.waitFor({ timeout: 30_000 });
      await button.click();
      await page.waitForTimeout(800);
      const at = await panel.boundingBox();
      const kept = (await panel.getByText(CORRECTED).count()) > 0;
      check('5 at 400 px, Test brings the panel into view with its composer usable and the test still there', !!at && at.y < 860 && at.y + 40 > 0 && (await panel.getByLabel('Message').isEditable()) && kept, { at, kept });
      await page.screenshot({ path: join(SHOTS, 'agent-test-panel-400.png'), fullPage: false });

      // Compare (c-286): a saved draft and the published version answer the same question side by side, each with its
      // spend. The draft is saved over the API, as the page's autosave would.
      const signIn = await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: 'j.richardson@harborpine.example', password: 'northfield-demo' }) });
      const J = { Authorization: `Bearer ${(await signIn.json()).data.token}`, 'Content-Type': 'application/json' };
      const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}/v1/agents/ag_advisor`;
      const advisor = (await (await fetch(agentsUrl, { headers: J })).json()).data;
      const drafted = await fetch(agentsUrl, { method: 'PATCH', headers: J, body: JSON.stringify({ instructions: `${advisor.instructions} UC253 DRAFT` }) });
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.goto(`${consoleUrl}/agents/ag_advisor`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await panel.waitFor({ timeout: 120_000 });
      await panel.getByTestId('compare-tab').click();
      await panel.getByLabel('Message').fill('UC253 COMPARE: what does the Harbor & Pine fund charge?');
      await panel.locator('button[aria-label="Send"]').click();
      const sideSpend = panel.getByTestId('compare-spent');
      await sideSpend.nth(1).waitFor({ timeout: 120_000 });
      const sides = await panel.getByTestId('compare-side').allInnerTexts();
      const costs = await sideSpend.allInnerTexts();
      check('7 Compare asks the newest draft and the published version the same question, each reply with its spend', drafted.ok && sides.length === 2 && /\(newest\)/.test(sides[0]) && costs.length === 2 && costs.every((c) => /tokens/.test(c)), { status: drafted.status, sides: sides.map((x) => x.slice(0, 80)), costs });
      await page.screenshot({ path: join(SHOTS, 'agent-test-panel-compare.png'), fullPage: false });
      check('6 no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);
finish();
