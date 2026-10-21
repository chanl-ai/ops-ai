// uc-229 a guarded answer streams as it is written and is replaced when its check fails, ui layer:
// docs/usecases/agents-service/a-guarded-answer-streams-and-is-replaced.md. The advisor (No investment advice pinned,
// not held) gets a harmless question; the fake model answers with share advice, which the after-answer check catches.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const ADVICE = 'You should buy Harbor & Pine shares';
const CORRECTED = "I can't give investment advice. A licensed adviser can talk your client through the fund.";

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      // The chat stream's frames, as the page receives them: a streamed body cannot be read back from the network log.
      await page.addInitScript(() => {
        const original = window.fetch;
        window.__frames = [];
        window.fetch = async (...args) => {
          const res = await original(...args);
          const url = String(args[0] instanceof Request ? args[0].url : args[0]);
          if (!/\/chat\/threads\/[^/]+\/messages$/.test(url) || !res.body) return res;
          const [mine, theirs] = res.body.tee();
          (async () => {
            const reader = mine.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            for (;;) {
              const { value, done } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split('\n');
              buffer = lines.pop() ?? '';
              for (const line of lines) if (line.startsWith('data:')) { try { window.__frames.push(JSON.parse(line.slice(5))); } catch {} }
            }
          })();
          return new Response(theirs, { status: res.status, statusText: res.statusText, headers: res.headers });
        };
      });
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('m.okafor@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/chat?agent=ag_advisor`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByLabel('Message');
      await box.waitFor({ timeout: 120_000 });
      await box.fill('UC229 FUND QUESTION: what should my client know about the Harbor & Pine fund?');
      await page.locator('button[aria-label="Send"]').click();
      await page.waitForFunction(() => (window.__frames ?? []).some((f) => f.type === 'done' || f.type === 'error'), null, { timeout: 120_000 });
      const frames = await page.evaluate(() => window.__frames);
      const texts = frames.filter((f) => f.type === 'text').map((f) => f.delta).join('');
      const replaces = frames.filter((f) => f.type === 'replace');
      const firstText = frames.findIndex((f) => f.type === 'text');
      const checking = frames.findIndex((f) => f.type === 'status' && f.phase === 'checking');

      // Step 1: the answer streamed before its check ran.
      check('1 the answer streams as it is written, before the after-answer check', firstText >= 0 && texts.includes(ADVICE) && (checking < 0 || firstText < checking), { firstText, checking, texts: texts.slice(0, 120) });
      // Step 2: the check found the topic, so the stream replaced what was shown.
      check('2 the stream replaces it once the check finds the topic', replaces.length === 1 && replaces[0].text === CORRECTED, replaces);
      // Step 3: what the person reads is the replacement alone.
      await page.getByText(CORRECTED).first().waitFor({ timeout: 30_000 });
      const shown = await page.locator('main').innerText();
      check('3 the conversation shows the corrected answer and none of the advice', shown.includes(CORRECTED) && !shown.includes(ADVICE), shown.slice(-400));
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByText(CORRECTED).first().waitFor({ timeout: 60_000 });
      const reloaded = await page.locator('main').innerText();
      check('4 after a reload the stored message is the corrected one', reloaded.includes(CORRECTED) && !reloaded.includes(ADVICE), reloaded.slice(-400));
      // A reviewer may not view the audit: the withdrawn advice never reaches her page, not even folded away.
      const mayasAudit = await page.getByTestId('guardrail-audit').count();
      const streamed = JSON.stringify(frames);
      check('5 a reviewer gets no audit of what was taken back, on the page or in the stream', mayasAudit === 0 && !streamed.includes('guardrailAudit'), { mayasAudit });

      // An admin may: the same turn in her own chat keeps what was shown and withdrawn, with the rule, after a reload.
      const admin = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      admin.on('pageerror', (e) => errors.push(e.message));
      await admin.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await admin.getByLabel('Email').fill('p.shah@harborpine.example');
      await admin.getByLabel('Password').fill('northfield-demo');
      await admin.getByRole('button', { name: /^Sign in/ }).first().click();
      await admin.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await admin.goto(`${consoleUrl}/chat?agent=ag_advisor`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const adminBox = admin.getByLabel('Message');
      await adminBox.waitFor({ timeout: 120_000 });
      await adminBox.fill('UC229 FUND QUESTION: what should my client know about the Harbor & Pine fund?');
      await admin.locator('button[aria-label="Send"]').click();
      await admin.getByText(CORRECTED).first().waitFor({ timeout: 30_000 });
      await admin.reload({ waitUntil: 'domcontentloaded' });
      await admin.getByText(CORRECTED).first().waitFor({ timeout: 60_000 });
      await admin.getByTestId('guardrail-audit').getByRole('button').click();
      const audit = await admin.getByTestId('guardrail-audit').innerText();
      check('6 an admin sees, after a reload, the advice that was shown and withdrawn, with its rule', audit.includes(ADVICE) && audit.includes('Shown, then withdrawn') && audit.includes('No investment advice'), audit);
      check('7 no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);
finish();
