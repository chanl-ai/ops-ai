// uc-620 any file a workflow or chat reads ends read or with a reason, ui layer:
// docs/usecases/agents-service/any-file-a-workflow-or-chat.md. The demo stack (platform sign-in, models-service on the
// demo's fake OpenAI rules), signed in as James: a PDF attached in the chat composer goes to Files as a chat
// attachment, the agent answers from its text, the message links the file into Files, and a type chat cannot read is
// refused on the chip in plain words.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const PASSWORD = 'northfield-demo';
const RUN = Math.random().toString(36).slice(2, 8);
const NOTICE = `notice-${RUN}.pdf`;
const MESSAGES = /\/chat\/threads\/[^/]+\/messages$/;
const tokenFor = async (email) => (await (await call(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
// Every setup and read call gives up after a minute, so a stalled service fails its step instead of the run.
const call = (url, init = {}) => fetch(url, { ...init, signal: AbortSignal.timeout(60_000) });
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    // An agent of the team's own with no knowledge bases, so the answer can come only from the attachment.
    const made = await data(await call(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Notice Desk ${RUN}`, role: 'Answers about notices' }) }));
    await data(await call(`${agents}/v1/agents/${made.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: made.version, note: 'uc-620' }) }));
    const tid = (await data(await call(`${agents}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: made.id, kbIds: [] }) }))).id;
    // Bytes of their own, so Files stores a new file rather than handing back a seeded copy with another purpose.
    const notice = Buffer.concat([readFileSync(join(ROOT, 'services/agents-service/tests/fixtures/mailbox/levy_notice.pdf')), Buffer.from(`\n% uc-620 ui ${RUN}\n`)]);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      page.setDefaultTimeout(60_000);
      await page.goto(`${consoleUrl}/chat/${tid}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      const chips = page.getByTestId('chat-attach-items');

      await step('9 a PDF attached in the composer is stored in Files and the agent answers from it on the fake model', async () => {
        const uploads = [];
        page.on('response', (r) => /\/v1\/files\/uploads/.test(r.url()) && uploads.push(`${r.request().method()} ${new URL(r.url()).pathname.replace(/fil_\w+/, 'fil_…')} ${r.status()}`));
        await page.locator('#chat-attach').setInputFiles({ name: NOTICE, mimeType: 'application/pdf', buffer: notice });
        await chips.locator('[data-phase="ready"]').waitFor({ timeout: 60_000 });
        await box.fill('uc620 who is the first debtor in this notice?');
        const sent = page.waitForResponse((r) => r.request().method() === 'POST' && MESSAGES.test(r.url()), { timeout: 120_000 });
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        // The reply streams; its end is waited for at most a minute, as the page shows it on its own.
        const res = await sent;
        await Promise.race([res.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
        const answered = await page.getByText('is Marcus Bell, held for 3,250.00').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const stored = (await data(await call(`${agents}/chat/threads/${tid}`, { headers: J }))).messages;
        const asked = stored.find((m) => m.role === 'user');
        const shown = answered ? '' : (await page.locator('main').innerText().catch((e) => `unread: ${e}`)).slice(-600);
        check('9 a PDF attached in the composer is stored in Files and the agent answers from it on the fake model', answered && /^fil_/.test(asked?.attachments?.[0]?.fileId ?? '') && uploads.some((u) => u.startsWith('POST /v1/files/uploads ')), { answered, attachments: asked?.attachments, uploads, reply: stored.at(-1)?.content?.slice(0, 200), shown, closed: page.isClosed() });
      });

      await step('10 the message links the file into Files, where it is listed as a chat attachment', async () => {
        const link = page.getByTestId('chat-message-attachment').filter({ hasText: NOTICE }).first();
        const href = await link.getAttribute('href');
        await link.click();
        await page.waitForURL((u) => u.pathname.startsWith('/files/'), { timeout: 60_000 });
        const opened = await page.getByText(NOTICE).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
        // The Files list says what each file is for.
        await page.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = page.getByRole('row').filter({ hasText: NOTICE }).first();
        const listed = await row.waitFor({ timeout: 60_000 }).then(async () => (await row.innerText()).replace(/\s+/g, ' '), () => '');
        check('10 the message links the file into Files, where it is listed as a chat attachment', /^\/files\/fil_/.test(href ?? '') && opened && /Chat attachment/.test(listed), { href, opened, listed });
      });

      await step('12 the file cited in the reply opens in Files from its source chip and its citation', async () => {
        const opens = async (open) => {
          await page.goto(`${consoleUrl}/chat/${tid}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByText('is Marcus Bell, held for 3,250.00').last().waitFor({ timeout: 60_000 });
          await open();
          const moved = await page.waitForURL((u) => u.pathname.startsWith('/files/fil_'), { timeout: 15_000 }).then(() => true, () => false);
          const missing = await page.getByText(/not found/i).first().isVisible().catch(() => false);
          const shown = moved && (await page.getByText(NOTICE).first().waitFor({ timeout: 60_000 }).then(() => true, () => false));
          return { moved, shown, missing, url: page.url() };
        };
        const chip = await opens(() => page.getByLabel(`Open ${NOTICE}`).first().click());
        const cite = await opens(async () => {
          await page.getByRole('button', { name: new RegExp(`^Citation 1: ${NOTICE.replace('.', '\\.')}`) }).last().click();
          await page.getByRole('dialog').getByRole('link', { name: 'Open in Files' }).click();
        });
        check('12 the file cited in the reply opens in Files from its source chip and its citation', [chip, cite].every((o) => o.moved && o.shown && !o.missing), { chip, cite });
      });

      await step('11 a type chat cannot read is refused on the chip in plain words', async () => {
        await page.goto(`${consoleUrl}/chat/${tid}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.locator('#chat-attach').setInputFiles({ name: 'photo.png', mimeType: 'image/png', buffer: Buffer.from('\x89PNG\r\n\x1a\n') });
        const chip = chips.locator('[data-phase="error"]').first();
        await chip.waitFor({ timeout: 30_000 });
        const said = await chip.innerText();
        check('11 a type chat cannot read is refused on the chip in plain words', /PNG is not accepted here\. Accepted: PDF/.test(said), said);
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { demo: true },
);

finish();
